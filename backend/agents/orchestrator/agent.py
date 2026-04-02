# ─────────────────────────────────────────────────────────────────────────────
# agents/orchestrator/agent.py
#
# Orchestrator — 日报编排器
# Fan-Out / Fan-In 模式：
#   Fan-Out：并行下发 HotTopics + DeepSummary + Trend Agent
#   Fan-In：聚合三路结果
#   Compose：调用 Report Composer 生成最终日报
# ─────────────────────────────────────────────────────────────────────────────

import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from agents.llms.base import LLMClient, create_llm_client

logger = logging.getLogger(__name__)


@dataclass
class DailyReportContext:
    """统一上下文：所有 Agent 共享的文章数据"""
    date: str
    articles_count: int
    articles: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    language: str = "mixed"


@dataclass
class AgentResult:
    """单个 Agent 的执行结果"""
    agent_name: str
    success: bool
    data: dict | None = None
    error: str | None = None
    duration_seconds: float = 0.0


class Orchestrator:
    """
    日报编排器 — Fan-Out / Fan-In 模式

    流程：
    1. build_context()  — 从 SQLite 读取最近 N 天文章
    2. fan_out()        — 并行下发 3 个分析 Agent
    3. fan_in()         — 聚合结果，异常处理
    4. compose()        — 调用 Report Composer 生成最终日报
    5. persist()        — 存储到数据库
    """

    def __init__(
        self,
        hot_topics_agent,
        deep_summary_agent,
        trend_agent,
        report_composer,
    ):
        self.ht_agent = hot_topics_agent
        self.ds_agent = deep_summary_agent
        self.t_agent = trend_agent
        self.composer = report_composer

    async def run(
        self,
        days: int = 7,
        language: str = "mixed",
    ) -> dict:
        """
        执行完整日报生成流程

        Args:
            days: 分析最近 N 天的文章
            language: 语言过滤（zh / en / mixed）

        Returns:
            {
                "report_id": str,
                "date": str,
                "hot_topics": {...},
                "deep_summaries": {...},
                "trend_insights": {...},
                "final_report": {...},
                "articles_count": int,
                "duration_seconds": float,
            }
        """
        start = datetime.now(timezone.utc)
        logger.info(
            f"[Orchestrator] 开始生成日报，days={days}, language={language}"
        )

        # ── Step 1: 构建上下文 ────────────────────────────────────────
        context = await self.build_context(days=days, language=language)
        if context.articles_count == 0:
            logger.warning("[Orchestrator] 指定时间范围内无文章")
            return {
                "report_id": f"report_{context.date}",
                "date": context.date,
                "error": "No articles found for the specified period",
                "articles_count": 0,
                "duration_seconds": 0.0,
            }

        logger.info(
            f"[Orchestrator] 上下文构建完成，共 {context.articles_count} 篇文章"
        )

        # ── Step 2: Fan-Out — 并行执行 3 个 Agent ─────────────────────
        agent_results = await self.fan_out(context)
        fan_out_duration = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(
            f"[Orchestrator] Fan-Out 完成，耗时 {fan_out_duration:.2f}s"
        )

        # ── Step 3: Fan-In — 聚合结果 ────────────────────────────────
        aggregated = self.fan_in(agent_results)

        # ── Step 4: Report Composer — 生成最终日报 ───────────────────
        final_report = await self.composer.compose(
            date=context.date,
            hot_topics=aggregated["hot_topics"],
            deep_summaries=aggregated["deep_summaries"],
            trend_insights=aggregated["trend_insights"],
        )

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(f"[Orchestrator] 日报生成完成，总耗时 {duration:.2f}s")

        return {
            "report_id": f"report_{context.date}",
            "date": context.date,
            "hot_topics": aggregated["hot_topics"],
            "deep_summaries": aggregated["deep_summaries"],
            "trend_insights": aggregated["trend_insights"],
            "final_report": final_report,
            "articles_count": context.articles_count,
            "agent_results": [
                {
                    "agent_name": r.agent_name,
                    "success": r.success,
                    "duration_seconds": r.duration_seconds,
                    "error": r.error,
                }
                for r in agent_results
            ],
            "duration_seconds": duration,
        }

    async def fan_out(self, context: DailyReportContext) -> list[AgentResult]:
        """
        并行下发 3 个分析 Agent

        使用 asyncio.gather 实现真正的并行执行，
        总耗时 = 最慢 Agent 的耗时，而非三者之和。
        """
        tasks = [
            self._run_agent_safe(self.ht_agent, context, "HotTopics"),
            self._run_agent_safe(self.ds_agent, context, "DeepSummary"),
            self._run_agent_safe(self.t_agent, context, "Trend"),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results

    async def _run_agent_safe(
        self,
        agent,
        context: DailyReportContext,
        agent_name: str,
    ) -> AgentResult:
        """安全执行单个 Agent，捕获异常，记录耗时"""
        start = datetime.now(timezone.utc)

        try:
            logger.info(f"[Orchestrator] 启动 {agent_name} Agent...")
            data = await agent.analyze(context)
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            logger.info(
                f"[Orchestrator] {agent_name} Agent 完成，耗时 {duration:.2f}s"
            )
            return AgentResult(
                agent_name=agent_name,
                success=True,
                data=data,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            logger.error(
                f"[Orchestrator] {agent_name} Agent 执行失败: {e}"
            )
            return AgentResult(
                agent_name=agent_name,
                success=False,
                error=str(e),
                duration_seconds=duration,
            )

    def fan_in(self, results: list[AgentResult]) -> dict:
        """
        聚合 3 个 Agent 的输出

        容错策略：
        - 一个 Agent 失败不影响整体
        - 缺失数据用空结构填充，保证日报仍可生成
        """
        aggregated = {
            "hot_topics": {},
            "deep_summaries": {},
            "trend_insights": {},
        }

        for result in results:
            if result.success and result.data:
                if result.agent_name == "HotTopics":
                    aggregated["hot_topics"] = result.data
                elif result.agent_name == "DeepSummary":
                    aggregated["deep_summaries"] = result.data
                elif result.agent_name == "Trend":
                    aggregated["trend_insights"] = result.data
            else:
                logger.warning(
                    f"[Fan-In] {result.agent_name} Agent 执行失败，使用空数据: "
                    f"{result.error}"
                )
                if result.agent_name == "HotTopics":
                    aggregated["hot_topics"] = {
                        "date": "",
                        "total_analyzed": 0,
                        "items": [],
                        "error": result.error,
                    }
                elif result.agent_name == "DeepSummary":
                    aggregated["deep_summaries"] = {
                        "date": "",
                        "total_events": 0,
                        "events": [],
                        "error": result.error,
                    }
                elif result.agent_name == "Trend":
                    aggregated["trend_insights"] = {
                        "date": "",
                        "tech_trend": {},
                        "app_trend": {},
                        "policy_trend": {},
                        "capital_trend": {},
                        "cross_dimension_signals": [],
                        "error": result.error,
                    }

        return aggregated

    async def build_context(
        self,
        days: int = 7,
        language: str = "mixed",
    ) -> DailyReportContext:
        """
        从 SQLite 读取最近 N 天的文章，构建统一上下文

        Args:
            days: 分析最近 N 天
            language: 语言过滤

        Returns:
            DailyReportContext
        """
        from core.database import get_database

        conn = get_database()
        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        query = """
            SELECT
                id, title, summary, source, source_url,
                published_at, url, author, tags, language,
                reading_time_minutes
            FROM articles
            WHERE published_at >= ?
        """
        params: list = [since]

        if language != "mixed":
            query += " AND language = ?"
            params.append(language)

        query += " ORDER BY published_at DESC"

        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        articles = []
        sources: set = set()

        for row in rows:
            d = dict(row)
            tags_str = d.get("tags") or "[]"
            try:
                import json as _json
                tags = _json.loads(tags_str) if isinstance(tags_str, str) else tags_str
            except Exception:
                tags = []

            articles.append({
                "id": d["id"],
                "title": d["title"],
                "summary": d.get("summary") or "",
                "source": d["source"],
                "published_at": d.get("published_at"),
                "url": d["url"],
                "author": d.get("author"),
                "tags": tags,
                "language": d.get("language"),
                "reading_time_minutes": d.get("reading_time_minutes"),
            })
            sources.add(d["source"])

        return DailyReportContext(
            date=today,
            articles_count=len(articles),
            articles=articles,
            sources=sorted(list(sources)),
            language=language,
        )
