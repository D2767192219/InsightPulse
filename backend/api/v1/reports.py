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


@router.post("/generate", response_model=dict)
async def generate_daily_report(
    days: int = Query(7, ge=1, le=30, description="分析最近 N 天的文章"),
    language: str = Query(
        "mixed",
        description="语言过滤：zh（中文）/ en（英文）/ mixed（混合）",
    ),
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
    from agents.report_composer.agent import ReportComposer
    from agents.llms.base import create_llm_client

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info(f"[Reports] 手动触发日报生成，日期={today}, days={days}")

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
            report_composer=ReportComposer(
                create_llm_client("report_composer")
            ),
        )

        # ── 执行日报生成流程 ──────────────────────────────────────
        result = await orchestrator.run(days=days, language=language)

        if "error" in result and result.get("articles_count", 0) == 0:
            return error_response(
                message=result["error"],
                code=400,
            )

        # ── 存储到数据库 ──────────────────────────────────────────
        conn = get_database()
        report_id = result["report_id"]

        await conn.execute("""
            INSERT OR REPLACE INTO daily_reports
            (id, date, report_json, markdown_report, articles_count,
             hot_topics, deep_summaries, trend_insights, generated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id,
            today,
            json.dumps(result, ensure_ascii=False),
            result.get("final_report", {}).get("markdown_report", ""),
            result["articles_count"],
            json.dumps(result.get("hot_topics", {}), ensure_ascii=False),
            json.dumps(result.get("deep_summaries", {}), ensure_ascii=False),
            json.dumps(result.get("trend_insights", {}), ensure_ascii=False),
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
            "status": "completed",
            "articles_analyzed": result["articles_count"],
            "duration_seconds": result.get("duration_seconds", 0),
            "final_report": result.get("final_report", {}),
        })

    except Exception as e:
        logger.error(f"[Reports] 日报生成失败: {e}", exc_info=True)
        return error_response(message=f"日报生成失败: {e}", code=500)


@router.get("/{date}", response_model=dict)
async def get_report(date: str):
    """
    获取指定日期的日报

    Args:
        date: 日期，格式 YYYY-MM-DD，例如 2026-04-02
    """
    conn = get_database()

    async with conn.execute(
        "SELECT * FROM daily_reports WHERE date = ?", (date,)
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
        "FROM daily_reports ORDER BY date DESC LIMIT ? OFFSET ?",
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
