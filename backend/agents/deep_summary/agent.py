# ─────────────────────────────────────────────────────────────────────────────
# agents/deep_summary/agent.py
#
# DeepSummary Agent — 重要事件深度总结
# 内部流水线：GroupNode → ExtractNode → StructureNode → ImpactNode
# 输出：What / Why / Who / Impact 结构化事件摘要
# ─────────────────────────────────────────────────────────────────────────────

import logging
from typing import Optional
from dataclasses import dataclass

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


@dataclass
class DailyReportContext:
    """由 Orchestrator 构建的统一上下文"""
    date: str
    articles_count: int
    articles: list[dict]
    sources: list[str]
    language: str = "mixed"


class DeepSummaryAgent:
    """
    深度总结 Agent

    内部节点流水线：
    1. GroupNode      — 筛选有实质内容的文章（前30篇）
    2. ExtractNode    — LLM 批量聚类+生成事件摘要
    3. StructureNode  — 输出 What/Why/Who/Impact 结构
    4. ImpactNode     — 评估影响范围和持续性
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def analyze(self, context: DailyReportContext) -> dict:
        """
        执行深度总结分析

        Args:
            context: Orchestrator 构建的统一上下文

        Returns:
            {
                "date": str,
                "total_events": int,
                "events": [EventSummaryItem, ...]
            }
        """
        logger.info(
            f"[DeepSummaryAgent] 开始分析，共 {context.articles_count} 篇文章"
        )

        # ── Step 1: GroupNode — 筛选有实质内容的文章 ───────────────────
        articles = self._filter_substantial(context.articles, top_k=30)
        logger.info(
            f"[DeepSummaryAgent] GroupNode 完成，筛选 {len(articles)} 篇实质性文章"
        )

        # ── Step 2: ExtractNode + StructureNode — LLM 批量生成摘要 ──────
        articles_text = self._build_articles_text(articles)
        user_prompt = f"""## 今日待分析文章（共 {len(articles)} 篇）

{articles_text}

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
      "sentiment": "positive|negative|neutral|controversial",
      "sentiment_score": 0.75,
      "participants": [
        {{"name": "DeepSeek", "role": "核心参与者", "type": "company"}},
        {{"name": "王小川", "role": "关键发声人", "type": "person"}}
      ],
      "key_facts": ["关键事实点1", "关键事实点2", "关键事实点3"],
      "persistence_score": 0.8,
      "source_count": 5
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
            )
        except Exception as e:
            logger.error(f"[DeepSummaryAgent] LLM 调用失败: {e}")
            return {
                "date": context.date,
                "total_events": 0,
                "events": [],
                "error": str(e),
            }

        parsed = self.llm._extract_json(raw_response)
        if not parsed or "events" not in parsed:
            logger.warning(
                f"[DeepSummaryAgent] LLM 返回格式异常: {raw_response[:200]}"
            )
            parsed = {"events": []}

        events = parsed.get("events", [])
        # 补充 event_id（如果没有的话）
        for i, evt in enumerate(events):
            if "event_id" not in evt:
                evt["event_id"] = f"evt_{context.date}_{i+1:03d}"

        result = {
            "date": context.date,
            "total_events": len(events),
            "events": events,
        }

        logger.info(
            f"[DeepSummaryAgent] 分析完成，识别 {len(events)} 个事件"
        )
        return result

    def _filter_substantial(
        self,
        articles: list[dict],
        top_k: int = 30,
    ) -> list[dict]:
        """
        GroupNode：筛选有实质内容的文章

        过滤策略：摘要长度 > 50 字符的文章优先
        """
        substantial = [
            a for a in articles
            if len(a.get("summary") or "") > 50
        ]
        # 按摘要长度降序
        substantial.sort(
            key=lambda a: len(a.get("summary") or ""),
            reverse=True,
        )
        return substantial[:top_k]

    def _build_articles_text(self, articles: list[dict]) -> str:
        """将文章列表格式化为 LLM 输入文本"""
        lines = []
        for i, a in enumerate(articles, 1):
            title = a.get("title", "无标题")
            summary = (a.get("summary") or "无摘要")[:500]
            source = a.get("source", "未知来源")
            url = a.get("url", "")
            lines.append(
                f"[{i}] 来源：{source}\n"
                f"    标题：{title}\n"
                f"    摘要：{summary}\n"
                f"    链接：{url}"
            )
        return "\n\n".join(lines)
