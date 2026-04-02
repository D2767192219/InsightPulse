# ─────────────────────────────────────────────────────────────────────────────
# agents/deep_summary/agent.py
#
# DeepSummary Agent — 重要事件深度总结
#
# 内部流水线（V2 增强）：
#   1. HotTopics-GuidedFilter — 优先围绕 Agent1 热点锚点过滤文章
#   2. EventExtractionNode    — LLM 批量聚类 + 生成事件摘要
#   3. ImportanceRankingNode  — 「热」vs「重要」双轨评分（V2 新增）
#   4. EventContextBuilder   — 生成 events_with_context
#
# 串行流水线：
#   输入: context + signal_ctx + ht_result（Agent1 热点锚点）
#   策略: 优先围绕 Agent1 的 Top 热点做深度分析，保留独立发现能力
#   输出: Top 3 重要事件 + events_with_context（供 Agent3 Trend 使用）
# ─────────────────────────────────────────────────────────────────────────────

import logging
import re
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
你是一名 AI 行业深度分析师，擅长从碎片化新闻中提炼核心事件。

你的任务是：
1. 将大量新闻按主题聚类，识别出独立的事件
2. 每个事件生成结构化摘要（What/Why/Who/Impact）
3. 评估事件的重要性和持续性

结构化摘要规范：
- What：事件核心事实（客观描述，不添加个人评价）
- Who：主要参与方及角色（人名/公司/产品）
- Why：事件背景和重要性（为什么值得关注）
- Impact：影响范围和程度（短期/长期影响）

注意：
- 合并同一事件的多个报道，不要重复
- 优先识别有实质内容的事件，忽略标题党
- 情感分析：positive（正面）/ negative（负面）/ neutral（中性）/ controversial（争议）
- 持续性分数：0.0=短暂 1.0=持续发酵

重要：你的输出必须是一个合法的 JSON 对象，不要包含任何 Markdown 代码块标记。
"""

DETAIL_REQUIREMENT_HINT = """\
【详细度硬性要求】
- what / why / impact 必须具体，禁止“值得关注/影响深远/持续观察”等空泛语句
- what 至少包含：时间点 + 行为主体 + 关键动作
- why 至少包含：与行业主线的关系（技术/商业/政策/资本之一）
- impact 必须拆成“短期影响（1-7天）”和“中期影响（1-4周）”
- 每个事件提供 2-4 条证据（evidence），必须引用输入文章标题或链接
"""

# 重要性评分标准（V2 新增：区分「热」和「重要」）
IMPORTANCE_SCORING_HINT = """\
【重要性评分标准】（区别于热度评分）

"热"（hot_score）代表传播广度，"重要"（importance_score）代表信息增量。
以下特征使一篇报道更具重要性：

- 首次公开信息（独家/首发）：+10 分
- 涉及多方关键参与方（公司/机构/个人）：+8 分
- 有具体数据/案例/数字支撑：+7 分
- 对行业有结构性影响（改变竞争格局/技术路线/监管方向）：+10 分
- 持续发酵中（跨多天报道、持续讨论）：+5 分
- 被低估的价值信号（讨论少但影响大）：+6 分

最终 importance_score = sum(以上适用项)，范围 0-40。
"""


class DailyReportContext:
    """统一上下文：所有 Agent 共享的文章数据"""
    date: str
    articles_count: int
    articles: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    language: str = "mixed"


class SignalContext:
    """信号工程层输出，供所有 Agent 共用"""
    date: str
    scored_articles: list[dict] = field(default_factory=list)
    top_articles: list[dict] = field(default_factory=list)
    top_events_articles: list[dict] = field(default_factory=list)
    signal_summary: dict = field(default_factory=dict)
    top_articles_by_source: dict = field(default_factory=dict)
    sentiment_summary: dict = field(default_factory=dict)
    clusters: list[dict] = field(default_factory=list)
    emerging_clusters: list[dict] = field(default_factory=list)


class DeepSummaryAgent:
    """
    深度总结 Agent

    内部节点流水线（V2 增强）：
    1. HotTopics-GuidedFilter — 优先围绕 Agent1 热点锚点过滤文章
    2. EventExtractionNode    — LLM 批量聚类 + 生成事件摘要
    3. ImportanceRankingNode — 「热」vs「重要」双轨评分
    4. EventContextBuilder   — 生成 events_with_context（供 Agent3）
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def analyze(
        self,
        context: DailyReportContext,
        signal_ctx: Optional[SignalContext] = None,
        ht_result: Optional[dict] = None,
        fast_mode: bool = False,
    ) -> dict:
        """
        执行深度总结分析

        Args:
            context: Orchestrator 构建的统一上下文
            signal_ctx: 信号工程层输出（V2 新增）
            ht_result: Agent1 HotTopics 输出（V2 新增，热点锚点）

        Returns:
            {
                "date": str,
                "total_events": int,
                "events": [EventSummaryItem, ...],
                "events_with_context": [...],
                "underestimated_events": [...],
            }
        """
        logger.info(
            f"[DeepSummaryAgent] 开始分析，共 {context.articles_count} 篇文章"
        )

        # ── Step 1: HotTopics-GuidedFilter ──────────────────────
        articles = self._hot_topics_guided_filter(
            context, signal_ctx, ht_result, top_k=20 if fast_mode else 30
        )
        logger.info(
            f"[DeepSummaryAgent] HotTopics-GuidedFilter 完成，筛选 {len(articles)} 篇"
        )

        # ── Step 2: LLM 批量事件提取 ──────────────────────────────
        articles_text = self._build_articles_text(
            articles,
            summary_limit=260 if fast_mode else 500,
        )

        # 构建热点锚点上下文提示（V2 新增）
        hotspot_hint = ""
        if ht_result and ht_result.get("hot_topics"):
            top_hots = ht_result["hot_topics"][:3]
            if top_hots:
                hotspot_hint = f"""\

【今日 HotTopics 识别的前3热点】（优先围绕以下话题识别重要事件）：

"""
                for i, h in enumerate(top_hots, 1):
                    hotspot_hint += f"  [{i}] {h.get('topic_name', '')}（composite_score={h.get('composite_score', 0):.2f}）\n"
                hotspot_hint += "\n请优先围绕以上热点识别相关重要事件。\n"

        user_prompt = f"""## 今日待分析文章（共 {len(articles)} 篇）

{articles_text}

{hotspot_hint}

{IMPORTANCE_SCORING_HINT}
{DETAIL_REQUIREMENT_HINT}

## 输出要求
将以上文章聚类为独立事件，每个事件输出以下 JSON 结构（最多 10 个事件）：

{{
  "events": [
    {{
      "event_id": "evt_001",
      "topic": "事件主题（一句话，25字以内）",
      "what": "发生了什么（What）：50字以内，客观描述核心事实",
      "who": "涉及谁（Who）：主要参与者和角色",
      "why": "为什么重要（Why）：事件背景和重要性，50字以内",
      "impact": "影响是什么（Impact）：影响范围和程度，80字以内",
      "importance_score": 28,  // 重要性评分（0-40），由 LLM 根据重要性标准估算
      "hot_score": 85.5,  // 热度评分（0-100），由 LLM 根据热度标准估算
      "sentiment": "positive|negative|neutral|controversial",
      "sentiment_score": 0.75,
      "participants": [
        {{"name": "DeepSeek", "role": "核心参与者", "type": "company"}},
        {{"name": "王小川", "role": "关键发声人", "type": "person"}}
      ],
      "key_facts": ["关键事实点1", "关键事实点2", "关键事实点3"],
      "evidence": [
        {{"title": "证据标题1", "url": "https://...", "source": "来源名", "why_relevant": "支撑该事件的原因"}}
      ],
      "impact_horizon": "short|medium|long",
      "relation_to_hot_topics": "direct|indirect|independent",
      "persistence_score": 0.8,
      "source_count": 5,
      "anchor_hot_topics": ["ht_001"],  // 关联的热点锚点 ID
      "is_underestimated": false  // 是否为被低估的重要事件
    }}
  ]
}}
"""

        try:
            raw_response = await self.llm.ainvoke(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                json_mode=fast_mode,
            )
        except Exception as e:
            logger.error(f"[DeepSummaryAgent] LLM 调用失败: {e}")
            return {
                "date": context.date,
                "total_events": 0,
                "events": [],
                "events_with_context": [],
                "underestimated_events": [],
                "error": str(e),
            }

        parsed = self.llm._extract_json(raw_response)
        if not parsed or "events" not in parsed:
            logger.warning(
                f"[DeepSummaryAgent] LLM 返回格式异常，尝试 json_mode 重试..."
            )
            try:
                raw_retry = await self.llm.ainvoke(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    json_mode=True,
                )
                parsed = self.llm._extract_json(raw_retry)
                if parsed and "events" in parsed:
                    logger.info("[DeepSummaryAgent] json_mode 重试成功")
                else:
                    logger.warning(
                        f"[DeepSummaryAgent] json_mode 仍解析失败: {raw_retry[:200]}"
                    )
                    parsed = {"events": []}
            except Exception as e2:
                logger.error(f"[DeepSummaryAgent] json_mode 重试失败: {e2}")
                parsed = {"events": []}

        events = parsed.get("events", [])

        # 补充 event_id（如果没有的话）
        for i, evt in enumerate(events):
            if "event_id" not in evt:
                evt["event_id"] = f"evt_{context.date}_{i+1:03d}"

        # 自动对齐热点锚点 + 细化弱描述字段
        events = self._link_events_to_hot_topics(events, ht_result)
        events = [self._enrich_event_detail(evt) for evt in events]

        # ── Step 3: EventContextBuilder — 为每个事件收集上下文 ───
        events_with_context = self._build_events_context(events, articles, signal_ctx, ht_result)

        # ── Step 4: 分离「被低估的重要事件」────────────────────
        underestimated = [e for e in events if e.get("is_underestimated", False)]

        result = {
            "date": context.date,
            "total_events": len(events),
            "events": events,
            "events_with_context": events_with_context,
            "underestimated_events": underestimated,
        }

        logger.info(
            f"[DeepSummaryAgent] 分析完成，识别 {len(events)} 个事件，"
            f"其中 {len(underestimated)} 个被低估事件"
        )
        return result

    def _link_events_to_hot_topics(
        self,
        events: list[dict],
        ht_result: Optional[dict],
    ) -> list[dict]:
        """将事件与热点建立显式连接，防止 anchor_hot_topics 为空。"""
        if not events:
            return events
        hot_topics = (ht_result or {}).get("hot_topics") or []
        if not hot_topics:
            return events

        hot_index: list[tuple[str, set[str]]] = []
        for h in hot_topics:
            topic_id = h.get("topic_id", "")
            topic_name = h.get("topic_name", "")
            kws = set(h.get("topic_keywords", []) or [])
            kws |= set(self._tokenize_text(topic_name))
            if topic_id:
                hot_index.append((topic_id, kws))

        for evt in events:
            evt_text = " ".join([
                evt.get("topic", ""),
                evt.get("what", ""),
                evt.get("why", ""),
                " ".join(evt.get("key_facts", []) or []),
            ]).lower()
            evt_tokens = set(self._tokenize_text(evt_text))
            matched = []
            for topic_id, kws in hot_index:
                if not kws:
                    continue
                overlap = len(evt_tokens & kws)
                if overlap >= 2:
                    matched.append(topic_id)

            if not evt.get("anchor_hot_topics"):
                evt["anchor_hot_topics"] = matched[:2]
            elif isinstance(evt.get("anchor_hot_topics"), list):
                evt["anchor_hot_topics"] = list(dict.fromkeys(evt["anchor_hot_topics"] + matched))[:2]

            if not evt.get("relation_to_hot_topics"):
                if evt.get("anchor_hot_topics"):
                    evt["relation_to_hot_topics"] = "direct"
                else:
                    evt["relation_to_hot_topics"] = "independent"
        return events

    def _enrich_event_detail(self, evt: dict) -> dict:
        """对过于简短/模糊的字段做轻量补全，提升可读性。"""
        evt_copy = dict(evt)
        key_facts = evt_copy.get("key_facts", []) or []
        fact_hint = "；".join(key_facts[:2]) if key_facts else ""

        def _normalize_text(value: str, min_len: int, fallback_prefix: str) -> str:
            text = (value or "").strip()
            if len(text) >= min_len:
                return text
            if fact_hint:
                return f"{fallback_prefix}：{text or '见关键事实'}；关键线索：{fact_hint}"
            return f"{fallback_prefix}：{text or '基于多源报道归纳'}"

        evt_copy["what"] = _normalize_text(evt_copy.get("what", ""), 28, "事件事实")
        evt_copy["why"] = _normalize_text(evt_copy.get("why", ""), 24, "重要性判断")
        evt_copy["impact"] = _normalize_text(evt_copy.get("impact", ""), 32, "影响评估")
        return evt_copy

    def _tokenize_text(self, text: str) -> list[str]:
        tokens = re.split(r"[\s,，。:：;；|/()（）\-]+", (text or "").lower())
        return [t for t in tokens if len(t) >= 2]

    def _hot_topics_guided_filter(
        self,
        context: DailyReportContext,
        signal_ctx: Optional[SignalContext],
        ht_result: Optional[dict],
        top_k: int = 30,
    ) -> list[dict]:
        """
        HotTopics-GuidedFilter：优先围绕 Agent1 热点锚点过滤文章

        策略：
        1. 如果有 ht_result，从信号评分文章中找出与热点最相关的文章
        2. 如果没有，回退到信号评分排序
        3. 补充未覆盖的高质量文章
        """
        articles = []

        if signal_ctx and signal_ctx.scored_articles:
            # 有信号上下文：按信号评分排序，优先使用 top_events_articles 保证事件相关性
            scored = list(signal_ctx.top_events_articles or signal_ctx.scored_articles)
        else:
            # 无信号上下文：按摘要长度排序
            scored = []
            for a in context.articles:
                summary_len = len(a.get("summary") or "")
                scored.append((summary_len, a))
            scored.sort(key=lambda x: x[0], reverse=True)
            scored = [a for _, a in scored]

        # 如果有热点锚点，优先取与热点相关的文章
        if ht_result and ht_result.get("hot_topics"):
            hot_keywords = set()
            for h in ht_result["hot_topics"]:
                name = h.get("topic_name", "")
                for word in name.replace("，", " ").replace(",", " ").split():
                    if len(word) > 2:
                        hot_keywords.add(word.lower())

            # 打标签：与热点相关的文章优先
            scored_with_priority = []
            for a in scored:
                text = (a.get("title", "") + " " + (a.get("summary") or "")).lower()
                priority = sum(1 for kw in hot_keywords if kw in text)
                scored_with_priority.append((priority, -len(a.get("summary", "")), a))

            scored_with_priority.sort(key=lambda x: (x[0], x[1]), reverse=True)
            articles = [a for _, _, a in scored_with_priority]
        else:
            articles = scored

        # 去重（URL 去重）
        seen_urls = set()
        unique_articles = []
        for a in articles:
            url = a.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_articles.append(a)
            if len(unique_articles) >= top_k:
                break

        return unique_articles[:top_k]

    def _build_events_context(
        self,
        events: list[dict],
        articles: list[dict],
        signal_ctx: Optional[SignalContext],
        ht_result: Optional[dict],
    ) -> list[dict]:
        """为每个事件构建上下文，包含相关文章和信号维度"""
        scored_map = {}
        if signal_ctx and signal_ctx.scored_articles:
            scored_map = {a.get("id"): a for a in signal_ctx.scored_articles}

        events_with_context = []
        for evt in events:
            evt_ctx = dict(evt)

            # 找出与该事件相关的文章
            topic = evt.get("topic", "")
            query_tokens = self._tokenize_text(
                " ".join([
                    topic,
                    evt.get("what", ""),
                    evt.get("why", ""),
                    " ".join(evt.get("key_facts", []) or []),
                ])
            )
            related_articles = []
            for a in articles:
                text = ((a.get("title", "") + " " + (a.get("summary") or "")).lower())
                if any(tok in text for tok in query_tokens):
                    related_articles.append({
                        "article_id": a.get("id", ""),
                        "title": a.get("title", ""),
                        "url": a.get("url", ""),
                        "source": a.get("source", ""),
                    })

            evt_ctx["related_articles"] = related_articles[:5]
            evt_ctx["cross_source_count"] = len(set(a.get("source") for a in related_articles))

            # 注入信号上下文
            if scored_map and related_articles:
                first_id = related_articles[0].get("article_id")
                if first_id and first_id in scored_map:
                    s = scored_map[first_id]
                    evt_ctx["signal_context"] = {
                        "authority": s.get("authority_score", 0),
                        "recency": s.get("recency_score", 0),
                        "community": s.get("community_score", 0),
                        "quality": s.get("content_quality_score", 0),
                    }

            # 关联热点锚点
            if ht_result and ht_result.get("hot_topics"):
                evt_ctx["anchor_hot_topics"] = evt.get("anchor_hot_topics", [])

            events_with_context.append(evt_ctx)

        return events_with_context

    def _build_articles_text(self, articles: list[dict], summary_limit: int = 500) -> str:
        """将文章列表格式化为 LLM 输入文本"""
        lines = []
        for i, a in enumerate(articles, 1):
            title = a.get("title", "无标题")
            summary = (a.get("summary") or "无摘要")[:summary_limit]
            source = a.get("source", "未知来源")
            url = a.get("url", "")
            composite = a.get("composite_score", 0)

            sig_info = ""
            if composite > 0:
                sig_info = f"\n    信号分：综合={composite:.2f}"

            lines.append(
                f"[{i}] 来源：{source}{sig_info}\n"
                f"    标题：{title}\n"
                f"    摘要：{summary}\n"
                f"    链接：{url}"
            )
        return "\n\n".join(lines)
