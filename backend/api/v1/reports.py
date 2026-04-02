# ─────────────────────────────────────────────────────────────────────────────
# api/v1/reports.py
#
# 日报相关 API 端点
# POST /api/v1/reports/generate  — 手动触发日报生成
# GET  /api/v1/reports/{date}    — 获取指定日期日报
# GET  /api/v1/reports/           — 日报列表（分页）
# ─────────────────────────────────────────────────────────────────────────────

import logging
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from core.database import get_database
from core.responses import success_response, error_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Reports"])


async def _ensure_daily_reports_schema(conn) -> None:
    """
    向后兼容旧数据库：
    - 如果 daily_reports 缺少 opportunity_signals 列，则自动补齐。
    - 如果 daily_reports.date 仍有 UNIQUE 约束，自动迁移为非唯一。
    """
    # 1) 检查并迁移 date UNIQUE 约束
    async with conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_reports'"
    ) as cursor:
        row = await cursor.fetchone()
    table_sql = (row["sql"] if row else "") or ""
    has_date_unique = "date            TEXT NOT NULL UNIQUE" in table_sql or "date TEXT NOT NULL UNIQUE" in table_sql

    if has_date_unique:
        async with conn.execute("PRAGMA table_info(daily_reports)") as cursor:
            cols = await cursor.fetchall()
        col_names = {c["name"] for c in cols}
        opp_expr = "opportunity_signals" if "opportunity_signals" in col_names else "'{}'"

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_reports_new (
                id                  TEXT PRIMARY KEY,
                date                TEXT NOT NULL,
                report_json         TEXT NOT NULL,
                markdown_report     TEXT,
                articles_count      INTEGER NOT NULL DEFAULT 0,
                hot_topics          TEXT,
                deep_summaries      TEXT,
                trend_insights      TEXT,
                opportunity_signals TEXT,
                generated_at        TEXT NOT NULL,
                created_at          TEXT NOT NULL
            )
        """)
        await conn.execute(f"""
            INSERT INTO daily_reports_new
            (id, date, report_json, markdown_report, articles_count,
             hot_topics, deep_summaries, trend_insights, opportunity_signals,
             generated_at, created_at)
            SELECT
                id, date, report_json, markdown_report, articles_count,
                hot_topics, deep_summaries, trend_insights, {opp_expr},
                generated_at, created_at
            FROM daily_reports
        """)
        await conn.execute("DROP TABLE daily_reports")
        await conn.execute("ALTER TABLE daily_reports_new RENAME TO daily_reports")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_generated_at ON daily_reports(generated_at DESC)")
        await conn.commit()

    # 2) 补齐 opportunity_signals 列（兼容中间态）
    async with conn.execute("PRAGMA table_info(daily_reports)") as cursor:
        rows = await cursor.fetchall()
    cols = {r["name"] for r in rows}
    if "opportunity_signals" not in cols:
        await conn.execute(
            "ALTER TABLE daily_reports ADD COLUMN opportunity_signals TEXT"
        )
        await conn.commit()


@router.post("/generate", response_model=dict)
async def generate_daily_report(
    days: int = Query(7, ge=1, le=30, description="分析最近 N 天的文章"),
    language: str = Query(
        "mixed",
        description="语言过滤：zh（中文）/ en（英文）/ mixed（混合）",
    ),
    fast_mode: bool = Query(False, description="性能模式：减少输入规模并优先快速生成"),
):
    """
    手动触发日报生成

    执行流程：
    1. Orchestrator 从 SQLite 读取最近 N 天文章
    2. Fan-Out：并行执行 HotTopics + DeepSummary + Trend Agent
    3. Fan-In：聚合三路结果
    4. Report Composer：生成最终日报
    5. 存储到数据库

    日报基于 Doubao Seed 2.0 模型（doubao-seed-2-0-lite-260215）生成。
    """
    from agents.orchestrator import Orchestrator
    from agents.hot_topics.agent import HotTopicsAgent
    from agents.deep_summary.agent import DeepSummaryAgent
    from agents.trend.agent import TrendAgent
    from agents.opportunity.agent import OpportunityScannerAgent
    from agents.report_composer.agent import ReportComposer
    from agents.llms.base import create_llm_client

    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    logger.info(f"[Reports] 手动触发日报生成，日期={today}, days={days}, fast_mode={fast_mode}")

    try:
        # ── 创建 Agent 实例 ────────────────────────────────────────
        orchestrator = Orchestrator(
            hot_topics_agent=HotTopicsAgent(
                create_llm_client("hot_topics")
            ),
            deep_summary_agent=DeepSummaryAgent(
                create_llm_client("deep_summary")
            ),
            trend_agent=TrendAgent(
                create_llm_client("trend")
            ),
            opportunity_agent=OpportunityScannerAgent(
                create_llm_client("opportunity")
            ),
            report_composer=ReportComposer(
                create_llm_client("report_composer")
            ),
        )

        # ── 执行日报生成流程 ──────────────────────────────────────
        result = await orchestrator.run(days=days, language=language, fast_mode=fast_mode)

        if "error" in result and result.get("articles_count", 0) == 0:
            return error_response(
                message=result["error"],
                code=400,
            )

        # ── 存储到数据库 ──────────────────────────────────────────
        conn = get_database()
        await _ensure_daily_reports_schema(conn)
        # 每次生成都保留为独立记录（同一天允许多份日报）
        report_id = f"report_{today}_{now_utc.strftime('%H%M%S_%f')}"

        await conn.execute("""
            INSERT INTO daily_reports
            (id, date, report_json, markdown_report, articles_count,
             hot_topics, deep_summaries, trend_insights, opportunity_signals,
             generated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id,
            today,
            json.dumps(result, ensure_ascii=False),
            result.get("final_report", {}).get("markdown_report", ""),
            result["articles_count"],
            json.dumps(result.get("hot_topics", {}), ensure_ascii=False),
            json.dumps(result.get("deep_summaries", {}), ensure_ascii=False),
            json.dumps(result.get("trend_insights", {}), ensure_ascii=False),
            json.dumps(result.get("opportunity_signals", {}), ensure_ascii=False),
            result.get("final_report", {}).get("generated_at", ""),
            datetime.now(timezone.utc).isoformat(),
        ))
        await conn.commit()

        logger.info(
            f"[Reports] 日报生成成功，ID={report_id}, "
            f"耗时={result.get('duration_seconds', 0):.2f}s"
        )

        return success_response(data={
            "report_id": report_id,
            "date": today,
            "fast_mode": fast_mode,
            "status": "completed",
            "articles_analyzed": result["articles_count"],
            "duration_seconds": result.get("duration_seconds", 0),
            "final_report": result.get("final_report", {}),
        })

    except Exception as e:
        logger.error(f"[Reports] 日报生成失败: {e}", exc_info=True)
        return error_response(message=f"日报生成失败: {e}", code=500)


@router.get("/by-id/{report_id}", response_model=dict)
async def get_report_by_id(report_id: str):
    """按 report_id 获取日报（推荐用于前端详情页）。"""
    conn = get_database()
    async with conn.execute(
        "SELECT * FROM daily_reports WHERE id = ?", (report_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return error_response(
            message=f"日报不存在: {report_id}",
            code=404,
        )

    d = dict(row)
    return success_response(data={
        "report_id": d["id"],
        "date": d["date"],
        "articles_count": d["articles_count"],
        "markdown_report": d["markdown_report"],
        "hot_topics": json.loads(d["hot_topics"] or "{}"),
        "deep_summaries": json.loads(d["deep_summaries"] or "{}"),
        "trend_insights": json.loads(d["trend_insights"] or "{}"),
        "opportunity_signals": json.loads(d.get("opportunity_signals") or "{}") if "opportunity_signals" in d.keys() else {},
        "generated_at": d["generated_at"],
    })


@router.get("/{date}", response_model=dict)
async def get_report(date: str):
    """
    获取指定日期的日报

    Args:
        date: 日期，格式 YYYY-MM-DD，例如 2026-04-02
    """
    conn = get_database()

    async with conn.execute(
        "SELECT * FROM daily_reports WHERE date = ? ORDER BY generated_at DESC LIMIT 1", (date,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return error_response(
            message=f"日报不存在: {date}",
            code=404,
        )

    d = dict(row)
    return success_response(data={
        "report_id": d["id"],
        "date": d["date"],
        "articles_count": d["articles_count"],
        "markdown_report": d["markdown_report"],
        "hot_topics": json.loads(d["hot_topics"] or "{}"),
        "deep_summaries": json.loads(d["deep_summaries"] or "{}"),
        "trend_insights": json.loads(d["trend_insights"] or "{}"),
        "opportunity_signals": json.loads(d.get("opportunity_signals") or "{}") if "opportunity_signals" in d.keys() else {},
        "generated_at": d["generated_at"],
    })


@router.get("/", response_model=dict)
async def list_reports(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=30, description="每页数量"),
):
    """获取日报列表（分页，按日期降序）"""
    conn = get_database()
    offset = (page - 1) * page_size

    async with conn.execute(
        "SELECT id, date, articles_count, generated_at "
        "FROM daily_reports ORDER BY generated_at DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    ) as cursor:
        rows = await cursor.fetchall()

    async with conn.execute(
        "SELECT COUNT(*) as cnt FROM daily_reports"
    ) as cursor:
        total = (await cursor.fetchone())["cnt"]

    pages = (total + page_size - 1) // page_size if total > 0 else 1

    items = [
        {
            "report_id": r["id"],
            "date": r["date"],
            "articles_count": r["articles_count"],
            "generated_at": r["generated_at"],
        }
        for r in rows
    ]

    return success_response(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    })
