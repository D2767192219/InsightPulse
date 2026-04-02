# ─────────────────────────────────────────────────────────────────────────────
# agents/orchestrator/agent.py
#
# Orchestrator — 日报编排器
#
# 串行流水线（V2）：
#   1. build_context()         — 从 SQLite 读取最近 N 天文章
#   2. scoring_prepass()      — 信号工程层：计算 6 维度信号和综合评分
#   3. Agent 1 HotTopics       — 串行第一步：Top 3-5 热点发现
#   4. Agent 2 DeepSummary     — 串行第二步：Top 3 重要事件深度总结
#   5. Agent 3 Trend          — 串行第三步：趋势研判（PEST/SWOT）
#   6. compose()              — ReportComposer 生成最终日报
#
# 核心设计决策：
#   三个分析 Agent 从并行改为串行，上游输出作为下游输入。
#   信号层在 Step 2 前置计算，为所有 Agent 提供决策上下文。
# ─────────────────────────────────────────────────────────────────────────────

import logging
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from agents.llms.base import LLMClient, create_llm_client
from services.clustering_engine import SemanticClusteringEngine, ClusterResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DailyReportContext:
    """统一上下文：所有 Agent 共享的文章数据"""
    date: str
    articles_count: int
    articles: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    language: str = "mixed"


@dataclass
class SignalContext:
    """
    信号工程层的输出，供所有 Agent 共用。

    由 scoring_prepass() 生成，包含 6 大维度的分项信号和综合评分。
    """
    date: str

    # 评分结果
    scored_articles: list[dict]      # 带 composite_score 的文章，按分降序
    top_articles: list[dict]        # Top-50（用于 HotTopics）
    top_events_articles: list[dict] # Top-30（用于 DeepSummary）

    # 信号分布摘要（用于 Agent 的上下文提示）
    signal_summary: dict
    # e.g. {
    #   "authority_mean": 1.45,
    #   "community_coverage_pct": 0.23,
    #   "academic_papers_pct": 0.61,
    #   "top_source": "arXiv",
    # }

    # 每个来源的最高分文章（用于多样性保障）
    top_articles_by_source: dict[str, list[dict]]

    # 情感分布摘要
    sentiment_summary: dict  # e.g. {"positive": 0.35, "neutral": 0.45}

    # 语义簇信息（V2 串行流水线新增）
    clusters: list[dict] = field(default_factory=list)
    emerging_clusters: list[dict] = field(default_factory=list)


@dataclass
class AgentResult:
    """单个 Agent 的执行结果"""
    agent_name: str
    success: bool
    data: dict | None = None
    error: str | None = None
    duration_seconds: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class Orchestrator:
    """
    日报编排器 — 串行流水线（V2）

    流程：
    1. build_context()         — 从 SQLite 读取最近 N 天文章
    2. scoring_prepass()       — 信号工程层：ScoringEngine + ClusteringEngine
    3. HotTopics.analyze()      — 串行第一步
    4. DeepSummary.analyze()    — 串行第二步
    5. Trend.analyze()          — 串行第三步
    6. compose()                — ReportComposer 生成最终日报
    """

    def __init__(
        self,
        hot_topics_agent,
        deep_summary_agent,
        trend_agent,
        report_composer,
        opportunity_agent=None,
    ):
        self.ht_agent = hot_topics_agent
        self.ds_agent = deep_summary_agent
        self.t_agent = trend_agent
        self.composer = report_composer
        self.opp_agent = opportunity_agent

    async def run(
        self,
        days: int = 7,
        language: str = "mixed",
        fast_mode: bool = False,
    ) -> dict:
        """
        执行完整日报生成流程（串行 V2）

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
                "signal_context": {...},  # 新增：信号上下文摘要
                "articles_count": int,
                "duration_seconds": float,
            }
        """
        start = datetime.now(timezone.utc)
        logger.info(
            f"[Orchestrator] 开始生成日报（V2串行模式），days={days}, language={language}, fast_mode={fast_mode}"
        )

        # ── Step 1: 构建上下文 ───────────────────────────────────────
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

        # ── Step 2: 信号预计算（scoring_prepass）───────────────
        signal_ctx = await self.scoring_prepass(context)
        ht_start = datetime.now(timezone.utc)

        # ── Step 3: Agent 1 — HotTopics（串行第一步）───────────
        logger.info("[Orchestrator] 启动 Agent 1: HotTopics...")
        ht_result = await self.ht_agent.analyze(context, signal_ctx, fast_mode=fast_mode)
        ht_duration = (datetime.now(timezone.utc) - ht_start).total_seconds()
        ht_success = "error" not in ht_result
        logger.info(
            f"[Orchestrator] Agent 1 HotTopics 完成，耗时 {ht_duration:.2f}s，"
            f"输出 {len(ht_result.get('items', []))} 个热点"
        )

        # ── Step 4: Agent 2 — DeepSummary（串行第二步）───────────
        ds_start = datetime.now(timezone.utc)
        logger.info("[Orchestrator] 启动 Agent 2: DeepSummary...")
        ds_result = await self.ds_agent.analyze(context, signal_ctx, ht_result, fast_mode=fast_mode)
        ds_duration = (datetime.now(timezone.utc) - ds_start).total_seconds()
        ds_success = "error" not in ds_result
        logger.info(
            f"[Orchestrator] Agent 2 DeepSummary 完成，耗时 {ds_duration:.2f}s，"
            f"输出 {len(ds_result.get('events', []))} 个事件"
        )

        # ── Step 5: Agent 3 — Trend（串行第三步）───────────────
        t_start = datetime.now(timezone.utc)
        logger.info("[Orchestrator] 启动 Agent 3: Trend...")
        t_result = await self.t_agent.analyze(context, signal_ctx, ht_result, ds_result, fast_mode=fast_mode)
        t_duration = (datetime.now(timezone.utc) - t_start).total_seconds()
        t_success = "error" not in t_result
        logger.info(
            f"[Orchestrator] Agent 3 Trend 完成，耗时 {t_duration:.2f}s"
        )

        # ── Step 6: Agent 4 — OpportunityScanner（可选）──────────
        opp_start = datetime.now(timezone.utc)
        opp_result = {"risk_signals": [], "opportunity_signals": []}
        if self.opp_agent:
            logger.info("[Orchestrator] 启动 Agent 4: OpportunityScanner...")
            try:
                opp_result = await self.opp_agent.analyze(
                    ht_result=ht_result,
                    ds_result=ds_result,
                    t_result=t_result,
                    signal_ctx=signal_ctx,
                    fast_mode=fast_mode,
                )
            except Exception as e:
                logger.error(f"[Orchestrator] OpportunityScanner 失败: {e}")
                opp_result["error"] = str(e)
        opp_duration = (datetime.now(timezone.utc) - opp_start).total_seconds()

        # ── Step 7: Report Composer ─────────────────────────────
        compose_start = datetime.now(timezone.utc)
        final_report = await self.composer.compose(
            date=context.date,
            hot_topics=ht_result,
            deep_summaries=ds_result,
            trend_insights=t_result,
            opportunity_signals=opp_result,
            fast_mode=fast_mode,
        )
        compose_duration = (datetime.now(timezone.utc) - compose_start).total_seconds()

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(
            f"[Orchestrator] 日报生成完成，总耗时 {duration:.2f}s "
            f"(HT={ht_duration:.1f}s DS={ds_duration:.1f}s T={t_duration:.1f}s C={compose_duration:.1f}s)"
        )

        # ── 存储 Agent 结果（用于调试和分析）─────────────────────
        agent_results = [
            AgentResult("HotTopics", ht_success, ht_result, duration_seconds=ht_duration),
            AgentResult("DeepSummary", ds_success, ds_result, duration_seconds=ds_duration),
            AgentResult("Trend", t_success, t_result, duration_seconds=t_duration),
        ]

        # ── 聚合（用于兼容现有 Report Composer 接口）─────────────
        aggregated = {
            "hot_topics": ht_result,
            "deep_summaries": ds_result,
            "trend_insights": t_result,
        }

        return {
            "report_id": f"report_{context.date}",
            "date": context.date,
            "fast_mode": fast_mode,
            "hot_topics": ht_result,
            "deep_summaries": ds_result,
            "trend_insights": t_result,
            "final_report": final_report,
            "signal_context": {
                "date": signal_ctx.date,
                "total_articles": signal_ctx.signal_summary.get("total_articles", 0),
                "authority_mean": signal_ctx.signal_summary.get("authority_mean", 0),
                "community_coverage_pct": signal_ctx.signal_summary.get("community_coverage_pct", 0),
                "academic_papers_pct": signal_ctx.signal_summary.get("academic_papers_pct", 0),
                "top_sources": signal_ctx.signal_summary.get("top_sources", []),
                "dimension_stats": signal_ctx.signal_summary.get("signal_dimension_stats", {}),
            },
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
            "opportunity_signals": opp_result,
            "duration_seconds": duration,
        }

    async def scoring_prepass(
        self,
        context: DailyReportContext,
    ) -> SignalContext:
        """
        在 Agent 执行前，对全量文章进行信号预计算。

        输出：
          SignalContext — 包含评分结果、信号摘要、来源分组等信息，
          供所有 Agent 使用。
        """
        from services.scoring_engine import ScoringEngine

        # 可选：语义聚类（用于新兴主题信号和多样性采样）
        clustering_engine = SemanticClusteringEngine()

        logger.info(
            f"[Orchestrator][scoring_prepass] 开始信号预计算，"
            f"共 {context.articles_count} 篇文章"
        )

        engine = ScoringEngine()

        # 对全部文章计算信号（不限 top_k，获取完整排序用于下游多样采样）
        scored = engine.score_articles(
            context.articles,
            date=context.date,
            top_k=context.articles_count,
        )
        await self._persist_signals_to_db(scored, context.date)

        # 语义聚类（可选）：失败时回退到纯热度排序
        try:
            sampled_articles, clusters = clustering_engine.cluster_articles(
                scored,
                max_results=50,
                results_per_cluster=5,
                score_field="composite_score",
            )
            emerging_clusters = clustering_engine.detect_emerging_clusters(
                current_clusters=clusters,
                previous_clusters=[],  # TODO: 接入历史缓存文件
            )
        except Exception as e:
            logger.warning(
                f"[Orchestrator][scoring_prepass] 聚类失败，回退：{e}"
            )
            sampled_articles = scored[:50]
            clusters = []
            emerging_clusters = []

        # 生成信号分布摘要
        summary = engine.get_signal_summary(scored)

        # 按来源分组（每个来源取 Top-5，用于多样性约束）
        top_by_source: dict[str, list[dict]] = {}
        for a in scored:
            src = a.get("source", "unknown")
            if src not in top_by_source:
                top_by_source[src] = []
            if len(top_by_source[src]) < 5:
                top_by_source[src].append(a)

        logger.info(
            f"[Orchestrator][scoring_prepass] 完成，"
            f"Top-1={scored[0]['composite_score']:.2f} "
            f"({scored[0].get('title', '')[:40]})，"
            f"clusters={len(clusters)}, emerging={len(emerging_clusters)}"
        )

        return SignalContext(
            date=context.date,
            scored_articles=scored,
            top_articles=sampled_articles[:50],
            top_events_articles=scored[:30],
            signal_summary=summary.to_dict(),
            top_articles_by_source=top_by_source,
            sentiment_summary={},
            clusters=[self._cluster_to_dict(c) for c in clusters],
            emerging_clusters=[self._cluster_to_dict(c) for c in emerging_clusters],
        )

    async def build_context(
        self,
        days: int = 7,
        language: str = "mixed",
    ) -> DailyReportContext:
        """
        从 SQLite 读取最近 N 天的文章，构建统一上下文。
        """
        conn = self._get_db_conn()
        now = datetime.now(timezone.utc)
        since = (now - timedelta(days=days)).isoformat()
        today = now.strftime("%Y-%m-%d")

        query = """
            SELECT
                id, title, summary, source, source_url,
                published_at, url, author, tags, language,
                reading_time_minutes, source_type, external_id
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
                tags = json.loads(tags_str) if isinstance(tags_str, str) else tags_str
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
                "source_type": d.get("source_type"),
                "external_id": d.get("external_id"),
            })
            sources.add(d["source"])

        return DailyReportContext(
            date=today,
            articles_count=len(articles),
            articles=articles,
            sources=sorted(list(sources)),
            language=language,
        )

    def _get_db_conn(self):
        """获取数据库连接"""
        from core.database import get_database
        return get_database()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _cluster_to_dict(self, c: ClusterResult) -> dict:
        """将 ClusterResult 转为可序列化 dict（供 SignalContext 暴露）"""
        return {
            "cluster_id": c.cluster_id,
            "size": c.size,
            "avg_composite_score": c.avg_composite_score,
            "topic_label": getattr(c, "topic_label", ""),
            "representative_article": c.representative_article,
            "articles": [a.get("id") for a in c.articles],
        }

    async def _persist_signals_to_db(self, scored_articles: list[dict], date: str) -> None:
        """
        将 scoring_prepass 结果写入 articles_signals，供前端数据表查询热度分。
        """
        if not scored_articles:
            return
        conn = self._get_db_conn()
        now_iso = datetime.now(timezone.utc).isoformat()

        payload = []
        for a in scored_articles:
            article_id = a.get("id")
            if not article_id:
                continue
            sig = a.get("signals")
            score_breakdown = {}
            engagement_score = 0.0
            citation_count = 0
            hours_ago = 0.0
            if sig:
                score_breakdown = getattr(sig, "signal_breakdown", {}) or {}
                engagement_score = float(getattr(sig, "community_score", 0.0) or 0.0)
                citation_count = int(getattr(sig, "citation_count", 0) or 0)
                hours_ago = float(getattr(sig, "hours_ago", 0.0) or 0.0)

            payload.append((
                f"{date}:{article_id}",
                article_id,
                date,
                engagement_score,
                float(a.get("authority_score", 0.0) or 0.0),
                float(a.get("recency_score", 0.0) or 0.0),
                hours_ago,
                float(a.get("content_quality_score", 0.0) or 0.0),
                citation_count,
                float(a.get("composite_score", 0.0) or 0.0),
                json.dumps(score_breakdown, ensure_ascii=False),
                now_iso,
            ))

        if not payload:
            return

        await conn.executemany(
            """
            INSERT OR REPLACE INTO articles_signals
            (id, article_id, date, engagement_score, authority_score, recency_score,
             hours_ago, content_quality_score, citation_count, composite_score,
             score_breakdown, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        await conn.commit()
        logger.info(
            "[Orchestrator][scoring_prepass] signals persisted: %d rows, date=%s",
            len(payload),
            date,
        )
