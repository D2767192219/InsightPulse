# ─────────────────────────────────────────────────────────────────────────────
# agents/hot_topics/agent.py
#
# HotTopics Agent — 热点发现
#
# 内部流水线（V2 增强）：
#   1. SignalPreFilter   — 取 ScoringEngine 输出的 Top-50 高分文章
#   2. LLMHotspotScoring — LLM 批量评分（注入信号上下文）
#   3. TopicAnchorGenerator — 生成热点锚点（带 composite_score 分项维度）
#
# 串行流水线：接受 signal_context，从 Top-50 高分文章中识别 Top 3-5 热点，
# 输出热点锚点供下游 Agent（DeepSummary / Trend）使用。
# ─────────────────────────────────────────────────────────────────────────────

import logging
import re
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
你是一名 AI 行业舆情分析师，擅长从海量新闻中识别最热话题。

你的任务是：
1. 阅读所有输入文章，识别出最具影响力的 AI 行业话题
2. 合并相似话题（避免重复报道同一事件）
3. 按热度从高到低排序
4. 输出结构化的热点榜单

评分标准（0-100分）：
- 技术突破性：重大进展 +15分
- 行业影响面：影响广泛（多公司/多领域） +15分
- 情感强度：争议性/突发性 +10分
- 来源权威性：权威媒体首发 +10分
- 时效性：当天首发 +10分

重要：你的输出必须是一个合法的 JSON 对象，不要包含任何 Markdown 代码块标记。
格式如下：
{
  "items": [
    {
      "rank": 1,
      "topic": "话题名称（一句话，30字以内）",
      "summary": "话题摘要（100字以内）",
      "key_article_title": "代表性文章标题",
      "key_article_url": "代表性文章链接",
      "source": "主要来源",
      "hot_score": 95.5,
      "direction": "rising|stable|declining",
      "trajectory": [5, 3, 1]
    }
  ]
}
"""


# 信号上下文注入模板（V2 新增）
SIGNAL_CONTEXT_HINT_TEMPLATE = """\
【今日信号背景】（以下信息来自信号工程层，仅供参考）

今日共分析 {articles_count} 篇文章，
- 高权威性文章（authority_score > 2.0）：{high_authority_count} 篇
- 有社区共鸣信号的文章（community_score > 0.5）：{community_count} 篇
- 学术论文占比：{academic_pct:.0%}
- 情感分布：{sentiment_dist}
- 新兴主题簇：{emerging_count} 个（语义上今日首次出现）

【评分权重参考】
请结合以上信号背景，重点关注：
1. 高权威性 + 高社区共鸣 的交叉文章（最具影响力）
2. 高信号得分 + 新兴主题 的交叉文章（可能是明日热点）
3. 高时效性（recency > 0.8）+ 高质量内容的文章（今日首发重要事件）
"""


# 热点锚点生成的系统提示（V2 新增）
ANCHOR_SYSTEM_PROMPT = """\
你是一名 AI 行业舆情分析师，擅长识别热点并提炼锚点。

你的任务：
1. 基于热点榜单中的 Top 3-5 热点，为每个热点生成结构化锚点
2. 每个锚点包含：该热点的 composite_score 分项维度（authority/community/recency）
3. 从输入文章中找出与该热点最相关的 2-3 篇代表性文章

输出 JSON（无 Markdown 代码块）：
{
  "hot_topics": [
    {
      "topic_id": "ht_001",
      "topic_name": "一句话话题名",
      "composite_score": 8.5,
      "signal_breakdown": {
        "authority_score": 2.4,
        "community_score": 0.82,
        "recency_score": 0.91,
        "quality_score": 0.73
      },
      "key_articles": [
        {"article_id": "...", "title": "...", "url": "..."},
        {"article_id": "...", "title": "...", "url": "..."}
      ],
      "direction": "rising|stable|declining",
      "related_clusters": [],
      "trend_note": "技术圈关注度高，但大众媒体尚未跟进"
    }
  ]
}
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


class HotTopicsAgent:
    """
    热点发现 Agent

    内部节点流水线（V2 增强）：
    1. SignalPreFilter  — 从 signal_context 取 Top-50 高分文章（替代 SortNode）
    2. LLMHotspotScoring — LLM 批量评分，注入信号上下文提示
    3. TopicAnchorGenerator — 生成热点锚点（带信号分项）
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def analyze(
        self,
        context: DailyReportContext,
        signal_ctx: Optional[SignalContext] = None,
        fast_mode: bool = False,
    ) -> dict:
        """
        执行热点分析

        Args:
            context: Orchestrator 构建的统一上下文
            signal_ctx: 信号工程层的输出（V2 新增，可选）

        Returns:
            {
                "date": str,
                "total_analyzed": int,
                "items": [HotTopicItem, ...],
                "hot_topics": [热点锚点列表，V2 新增],
                "hot_topic_articles": [所有锚点的核心文章],
            }
        """
        logger.info(f"[HotTopicsAgent] 开始分析，共 {context.articles_count} 篇文章")

        # ── Step 1: SignalPreFilter — 取 Top-50 高分文章 ──────────────
        top_k = 30 if fast_mode else 50
        articles = self._signal_filter(context, signal_ctx, top_k=top_k)
        logger.info(f"[HotTopicsAgent] SignalPreFilter 完成，筛选 {len(articles)} 篇")

        # ── Step 2: LLM 批量评分 + 锚点生成 ─────────────────────────
        articles_text = self._build_articles_text(
            articles,
            summary_limit=220 if fast_mode else 300,
        )

        # 构建信号上下文提示（V2）
        signal_hint = ""
        if signal_ctx and signal_ctx.signal_summary:
            sm = signal_ctx.signal_summary
            scored = signal_ctx.scored_articles
            signal_hint = SIGNAL_CONTEXT_HINT_TEMPLATE.format(
                articles_count=sm.get("total_articles", 0),
                high_authority_count=len([a for a in scored if a.get("authority_score", 0) > 2.0]),
                community_count=len([a for a in scored if a.get("community_score", 0) > 0.5]),
                academic_pct=sm.get("academic_papers_pct", 0),
                sentiment_dist=sm.get("sentiment_distribution", {}),
                emerging_count=len(signal_ctx.emerging_clusters or []),
            )

        user_prompt = f"""## 今日待分析文章（共 {len(articles)} 篇）

{articles_text}

{signal_hint}

## 输出要求
分析以上文章，输出 JSON 格式的热点榜单（Top 10）。
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
            logger.error(f"[HotTopicsAgent] LLM 调用失败: {e}")
            return {
                "date": context.date,
                "total_analyzed": context.articles_count,
                "items": [],
                "hot_topics": [],
                "hot_topic_articles": [],
                "error": str(e),
            }

        parsed = self.llm._extract_json(raw_response)
        if not parsed or "items" not in parsed:
            logger.warning(f"[HotTopicsAgent] LLM 返回格式异常，尝试 json_mode 重试...")
            try:
                raw_retry = await self.llm.ainvoke(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    json_mode=True,
                )
                parsed = self.llm._extract_json(raw_retry)
                if parsed and "items" in parsed:
                    logger.info("[HotTopicsAgent] json_mode 重试成功")
                else:
                    logger.warning(f"[HotTopicsAgent] json_mode 仍解析失败: {raw_retry[:200]}")
                    parsed = {"items": []}
            except Exception as e2:
                logger.error(f"[HotTopicsAgent] json_mode 重试失败: {e2}")
                parsed = {"items": []}

        items = parsed.get("items", [])

        # ── Step 3: TopicAnchorGenerator — 为 Top 5 生成锚点 ───────────
        hot_topics_anchors = self._generate_topic_anchors(items, articles, signal_ctx)

        # ── Step 4: 收集 hot_topic_articles（供下游 Agent 使用）───────
        hot_topic_article_ids = set()
        for anchor in hot_topics_anchors:
            for ka in anchor.get("key_articles", []):
                hot_topic_article_ids.add(ka.get("article_id"))

        result = {
            "date": context.date,
            "total_analyzed": context.articles_count,
            "items": items,
            "hot_topics": hot_topics_anchors,
            "hot_topic_articles": list(hot_topic_article_ids),
        }

        logger.info(f"[HotTopicsAgent] 分析完成，识别 {len(result['hot_topics'])} 个热点锚点")
        return result

    def _signal_filter(
        self,
        context: DailyReportContext,
        signal_ctx: Optional[SignalContext],
        top_k: int = 50,
    ) -> list[dict]:
        """
        SignalPreFilter：基于信号评分筛选高质量文章

        策略：
        1. 如果有 signal_ctx，优先使用 signal_ctx.top_articles（含多样性采样）
           若为空则退回 scored_articles
        2. 如果没有，回退到摘要长度 + 来源多样性过滤
        3. 每来源最多 3 篇，防止单一来源垄断
        """
        if signal_ctx and (signal_ctx.top_articles or signal_ctx.scored_articles):
            # 有信号上下文：使用多样性采样后的 Top 文章
            articles = list(signal_ctx.top_articles or signal_ctx.scored_articles)
            articles.sort(key=lambda a: a.get("composite_score", 0), reverse=True)
        else:
            # 无信号上下文：按摘要长度 + 时效性排序
            articles = []
            for a in context.articles:
                summary_len = len(a.get("summary") or "")
                has_summary = 1 if summary_len > 50 else 0
                pub_time = a.get("published_at") or ""
                articles.append((has_summary, pub_time, a))
            articles.sort(key=lambda x: (x[0], x[1]), reverse=True)
            articles = [a for _, _, a in articles]

        # 来源多样性约束：每来源最多 3 篇
        seen_sources: dict[str, int] = {}
        filtered = []
        for a in articles:
            src = a.get("source", "unknown")
            seen_sources[src] = seen_sources.get(src, 0) + 1
            if seen_sources[src] <= 3:
                filtered.append(a)
            if len(filtered) >= top_k:
                break

        return filtered

    def _generate_topic_anchors(
        self,
        items: list[dict],
        articles: list[dict],
        signal_ctx: Optional[SignalContext],
    ) -> list[dict]:
        """为 Top 5 热点生成结构化锚点"""
        anchors = []
        article_map = {a.get("id", ""): a for a in articles}

        for i, item in enumerate(items[:5]):
            topic_name = item.get("topic", "")
            key_title = item.get("key_article_title", "")

            # 找到最相关的文章
            key_articles = []
            for a in articles:
                title = a.get("title", "")
                if key_title and key_title in title:
                    key_articles.append({
                        "article_id": a.get("id", ""),
                        "title": title,
                        "url": a.get("url", ""),
                    })
                    if len(key_articles) >= 2:
                        break

            # 如果没找到匹配，从 Top 5 文章中选择
            if not key_articles:
                for a in articles[:3]:
                    key_articles.append({
                        "article_id": a.get("id", ""),
                        "title": a.get("title", ""),
                        "url": a.get("url", ""),
                    })
                    if len(key_articles) >= 2:
                        break

            # 从 signal_ctx 获取该文章的信号分项
            signal_breakdown = {}
            if signal_ctx and key_articles:
                for ka in key_articles:
                    aid = ka.get("article_id")
                    scored = {a.get("id"): a for a in signal_ctx.scored_articles}
                    if aid in scored:
                        s = scored[aid]
                        signal_breakdown = {
                            "authority_score": s.get("authority_score", 0),
                            "community_score": s.get("community_score", 0),
                            "recency_score": s.get("recency_score", 0),
                            "quality_score": s.get("content_quality_score", 0),
                        }
                        break

            anchors.append({
                "topic_id": f"ht_{i+1:03d}",
                "topic_name": topic_name,
                "topic_keywords": self._extract_keywords(topic_name),
                "composite_score": item.get("hot_score", 0),
                "signal_breakdown": signal_breakdown,
                "key_articles": key_articles,
                "direction": item.get("direction", "stable"),
                "related_clusters": [],
                "trend_note": item.get("summary", ""),
            })

        return anchors

    def _extract_keywords(self, text: str) -> list[str]:
        """从热点名称提取关键词，供下游事件锚定。"""
        if not text:
            return []
        tokens = re.split(r"[\s,，。:：;；|/()（）\-]+", text.lower())
        return [t for t in tokens if len(t) >= 2][:8]

    def _build_articles_text(self, articles: list[dict], summary_limit: int = 300) -> str:
        """将文章列表格式化为 LLM 输入文本"""
        lines = []
        for i, a in enumerate(articles, 1):
            title = a.get("title", "无标题")
            summary = (a.get("summary") or "无摘要")[:summary_limit]
            source = a.get("source", "未知来源")
            pub_time = a.get("published_at", "未知时间")[:16]
            url = a.get("url", "")
            composite = a.get("composite_score", 0)

            # 如果有信号分项，追加到文本中
            sig_info = ""
            if composite > 0:
                sig_info = f"\n    信号分：综合={composite:.2f} | 权威性={a.get('authority_score', 0):.2f} | 时效性={a.get('recency_score', 0):.2f} | 质量={a.get('content_quality_score', 0):.2f}"

            lines.append(
                f"[{i}] 来源：{source} | 时间：{pub_time}{sig_info}\n"
                f"    标题：{title}\n"
                f"    摘要：{summary}\n"
                f"    链接：{url}"
            )
        return "\n\n".join(lines)
