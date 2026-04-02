# ─────────────────────────────────────────────────────────────────────────────
# agents/hot_topics/agent.py
#
# HotTopics Agent — 热点发现
# 内部流水线：SortNode → ScoreNode → DedupeNode → RankNode
# ─────────────────────────────────────────────────────────────────────────────

import logging
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


@dataclass
class DailyReportContext:
    """统一上下文：所有 Agent 共享的文章数据（由 Orchestrator 构建）"""
    date: str
    articles_count: int
    articles: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    language: str = "mixed"


class HotTopicsAgent:
    """
    热点发现 Agent

    内部节点流水线（参考 BettaFish 5-Node）：
    1. SortNode     — 按质量（摘要存在）+ 时间排序，取前 50 篇
    2. ScoreNode    — 批量 LLM 打分，输出热度分数
    3. DedupeNode   — 合并相似话题
    4. RankNode     — 输出 Top 10 热点
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def analyze(self, context: DailyReportContext) -> dict:
        """
        执行热点分析

        Args:
            context: Orchestrator 构建的统一上下文

        Returns:
            {
                "date": str,
                "total_analyzed": int,
                "items": [HotTopicItem, ...]
            }
        """
        logger.info(f"[HotTopicsAgent] 开始分析，共 {context.articles_count} 篇文章")

        # ── Step 1: SortNode — 筛选高质量文章 ──────────────────────────
        articles = self._sort_and_filter(context.articles, top_k=50)
        logger.info(f"[HotTopicsAgent] SortNode 完成，筛选 {len(articles)} 篇高质量文章")

        # ── Step 2: ScoreNode + RankNode — LLM 批量分析 ────────────────
        articles_text = self._build_articles_text(articles)
        user_prompt = f"""## 今日待分析文章（共 {len(articles)} 篇）

{articles_text}

## 输出要求
分析以上文章，输出 JSON 格式的热点榜单（Top 10）。
"""

        try:
            raw_response = await self.llm.ainvoke(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as e:
            logger.error(f"[HotTopicsAgent] LLM 调用失败: {e}")
            return {
                "date": context.date,
                "total_analyzed": context.articles_count,
                "items": [],
                "error": str(e),
            }

        # ── Step 3: 解析结果 ────────────────────────────────────────────
        parsed = self.llm._extract_json(raw_response)
        if not parsed or "items" not in parsed:
            logger.warning(f"[HotTopicsAgent] LLM 返回格式异常，尝试修复: {raw_response[:200]}")
            parsed = {"items": []}

        result = {
            "date": context.date,
            "total_analyzed": context.articles_count,
            "items": parsed.get("items", []),
        }

        logger.info(f"[HotTopicsAgent] 分析完成，识别 {len(result['items'])} 个热点")
        return result

    def _sort_and_filter(self, articles: list[dict], top_k: int = 50) -> list[dict]:
        """SortNode：按文章质量（摘要长度）+ 时间排序，取前 top_k 篇"""
        scored = []
        for a in articles:
            summary_len = len(a.get("summary") or "")
            has_summary = 1 if summary_len > 50 else 0
            # 发布时间作为次要排序键
            pub_time = a.get("published_at") or ""
            scored.append((has_summary, pub_time, a))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [a for _, _, a in scored[:top_k]]

    def _build_articles_text(self, articles: list[dict]) -> str:
        """将文章列表格式化为 LLM 输入文本"""
        lines = []
        for i, a in enumerate(articles, 1):
            title = a.get("title", "无标题")
            summary = (a.get("summary") or "无摘要")[:300]
            source = a.get("source", "未知来源")
            pub_time = a.get("published_at", "未知时间")[:16]
            url = a.get("url", "")
            lines.append(
                f"[{i}] 来源：{source} | 时间：{pub_time}\n"
                f"    标题：{title}\n"
                f"    摘要：{summary}\n"
                f"    链接：{url}"
            )
        return "\n\n".join(lines)
