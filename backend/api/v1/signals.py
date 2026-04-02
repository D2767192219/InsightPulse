# ─────────────────────────────────────────────────────────────────────────────
# api/v1/signals.py
#
# 信号相关 API 端点
#
# 提供信号数据的两大用途：
#   1. Agent 使用：scoring_prepass 阶段为各 Agent 提供信号上下文
#   2. 前端可视化：仪表盘展示信号分布、趋势、高分文章等
#
# 端点：
#   POST /api/v1/signals/compute   — 对指定日期范围文章批量计算信号
#   GET  /api/v1/signals/stats     — 信号分布统计（前端可视化）
#   GET  /api/v1/signals/daily     — 每日信号趋势（前端可视化）
#   GET  /api/v1/signals/top       — 高分文章排行（带信号分项明细）
#   GET  /api/v1/signals/sources    — 来源权威性分布
#   GET  /api/v1/signals/weights    — 当前权重配置（用于前端调参）
# ─────────────────────────────────────────────────────────────────────────────

import logging
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from core.database import get_database
from core.responses import success_response, error_response
from services.scoring_engine import ScoringEngine, AUTHORITY_BY_TYPE, CONTENT_HALFLIFE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signals", tags=["Signals"])


# ─────────────────────────────────────────────────────────────────────────────
# 计算接口（供 Agent 使用，也可前端触发）
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/network", response_model=dict)
async def get_network_graph(
    days: int = Query(365, ge=1, le=3650, description="最近 N 天数据用于构图"),
    max_articles: int = Query(220, ge=50, le=1200, description="参与构图的文章上限"),
):
    """
    数据仓库关系图（全库视角）：
    - 节点：文章 / 来源 / 标签
    - 边：article->source, article->tag, source->tag(聚合关系)
    """
    conn = get_database()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()

    async with conn.execute("SELECT MAX(date) AS d FROM articles_signals") as cursor:
        row = await cursor.fetchone()
    latest_signal_date = (dict(row).get("d") if row else None)

    if latest_signal_date:
        sql = """
            SELECT
                a.id, a.title, a.source, a.tags, a.published_at,
                s.composite_score
            FROM articles a
            LEFT JOIN articles_signals s
              ON s.article_id = a.id AND s.date = ?
            WHERE a.published_at >= ?
            ORDER BY COALESCE(s.composite_score, 0) DESC, a.published_at DESC
            LIMIT ?
        """
        params = (latest_signal_date, since, max_articles)
    else:
        sql = """
            SELECT
                a.id, a.title, a.source, a.tags, a.published_at,
                NULL AS composite_score
            FROM articles a
            WHERE a.published_at >= ?
            ORDER BY a.published_at DESC
            LIMIT ?
        """
        params = (since, max_articles)

    async with conn.execute(sql, params) as cursor:
        rows = await cursor.fetchall()

    nodes: dict[str, dict] = {}
    links: list[dict] = []
    source_tag_weight: dict[tuple[str, str], int] = {}

    def ensure_node(node_id: str, label: str, node_type: str, size: float = 1.0):
        if node_id not in nodes:
            nodes[node_id] = {
                "id": node_id,
                "label": label,
                "type": node_type,
                "size": size,
            }
        else:
            nodes[node_id]["size"] = max(nodes[node_id].get("size", 1.0), size)

    for row in rows:
        d = dict(row)
        article_id = d.get("id", "")
        source = d.get("source", "unknown")
        title = (d.get("title") or "")[:70]
        comp = float(d.get("composite_score") or 0.0)

        art_node = f"art:{article_id}"
        src_node = f"src:{source}"
        ensure_node(art_node, title or article_id, "article", size=max(1.0, comp))
        ensure_node(src_node, source, "source", size=2.5)
        links.append({"source": art_node, "target": src_node, "type": "published_by", "weight": 1})

        tags_value = d.get("tags")
        tags = []
        if isinstance(tags_value, str):
            try:
                parsed = json.loads(tags_value)
                tags = parsed if isinstance(parsed, list) else []
            except Exception:
                tags = []
        elif isinstance(tags_value, list):
            tags = tags_value

        clean_tags = [str(t).strip() for t in tags if str(t).strip()]
        for tg in clean_tags[:6]:
            tag_node = f"tag:{tg}"
            ensure_node(tag_node, tg, "tag", size=1.8)
            links.append({"source": art_node, "target": tag_node, "type": "tagged_with", "weight": 1})
            key = (src_node, tag_node)
            source_tag_weight[key] = source_tag_weight.get(key, 0) + 1

    # 来源和标签的聚合关系边（用于体现数据仓库结构）
    for (src_node, tag_node), weight in source_tag_weight.items():
        if weight >= 2:
            links.append({
                "source": src_node,
                "target": tag_node,
                "type": "source_tag_affinity",
                "weight": weight,
            })

    return success_response(data={
        "days": days,
        "latest_signal_date": latest_signal_date,
        "nodes": list(nodes.values()),
        "links": links,
        "meta": {
            "article_count": len([n for n in nodes.values() if n["type"] == "article"]),
            "source_count": len([n for n in nodes.values() if n["type"] == "source"]),
            "tag_count": len([n for n in nodes.values() if n["type"] == "tag"]),
        },
    })

@router.post("/compute", response_model=dict)
async def compute_signals(
    days: int = Query(7, ge=1, le=30, description="计算最近 N 天的文章信号"),
    language: str = Query(
        "mixed",
        description="语言过滤：zh（中文）/ en（英文）/ mixed（混合）",
    ),
    save_to_db: bool = Query(True, description="是否将信号结果写入 articles_signals 表"),
):
    """
    批量计算信号

    - 读取指定日期范围的原始文章
    - 调用 ScoringEngine 计算 6 大维度信号和综合评分
    - 可选写入数据库（供后续查询使用）
    - 返回带信号的文章列表 + 信号分布摘要
    """
    conn = get_database()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()

    # 查询原始文章
    query = """
        SELECT
            a.id, a.title, a.summary, a.source, a.source_url,
            a.published_at, a.url, a.author, a.tags, a.language,
            a.reading_time_minutes, a.source_type, a.external_id,
            a.feed_id
        FROM articles a
        WHERE a.published_at >= ?
    """
    params: list = [since]

    if language != "mixed":
        query += " AND a.language = ?"
        params.append(language)

    query += " ORDER BY a.published_at DESC"

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return error_response(message="指定日期范围内无文章", code=404)

    # 转换为 dict
    articles = []
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
            "feed_id": d.get("feed_id"),
        })

    # 计算信号
    engine = ScoringEngine()
    scored_articles = engine.score_articles(articles, top_k=len(articles))
    summary = engine.get_signal_summary(scored_articles)

    # 可选：写入数据库
    if save_to_db:
        await _save_signals_to_db(conn, scored_articles, now.strftime("%Y-%m-%d"))
        logger.info(f"[Signals] 写入 {len(scored_articles)} 条信号记录到数据库")

    return success_response(data={
        "total_articles": len(scored_articles),
        "date_range": {
            "from": since[:10],
            "to": now.strftime("%Y-%m-%d"),
        },
        "summary": summary.to_dict(),
        "top_articles": [
            {
                "id": a["id"],
                "title": a.get("title", "")[:80],
                "source": a.get("source", ""),
                "composite_score": a.get("composite_score", 0),
                "authority_score": a.get("authority_score", 0),
                "recency_score": a.get("recency_score", 0),
                "content_quality_score": a.get("content_quality_score", 0),
            }
            for a in scored_articles[:20]
        ],
    })


# ─────────────────────────────────────────────────────────────────────────────
# 前端可视化接口
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=dict)
async def get_signal_stats(
    days: int = Query(7, ge=1, le=30, description="统计最近 N 天"),
    language: str = Query("mixed", description="语言过滤"),
):
    """
    信号分布统计 — 前端仪表盘核心数据

    返回：
    - 各维度分布（均值/p50/p90/min/max）
    - 来源类型分布（official/media/academic/social/aggregate 各多少篇）
    - 情感分布（controversial/positive/negative/neutral 占比）
    - 高分文章预览 Top 10
    - 新兴主题数量
    - 社区共鸣覆盖率
    """
    conn = get_database()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    date_str = now.strftime("%Y-%m-%d")

    # 从数据库读取已计算的信号
    async with conn.execute("""
        SELECT
            s.article_id,
            s.authority_score,
            s.recency_score,
            s.content_quality_score,
            s.community_score,
            s.citation_count,
            s.sentiment_label,
            s.is_emerging,
            s.composite_score,
            s.content_type,
            a.source,
            a.source_type,
            a.title
        FROM articles_signals s
        JOIN articles a ON s.article_id = a.id
        WHERE s.date = ?
    """, (date_str,)) as cursor:
        rows = await cursor.fetchall()

    # 如果当天没有信号数据，实时计算
    if not rows:
        return await _compute_and_return_stats(conn, days, language, now, since, date_str)

    signals = [dict(row) for row in rows]
    return _format_stats_response(signals, date_str, days)


@router.get("/daily", response_model=dict)
async def get_signal_daily_trend(
    days: int = Query(14, ge=3, le=90, description="展示最近 N 天的每日信号趋势"),
    language: str = Query("mixed", description="语言过滤"),
):
    """
    每日信号趋势 — 前端折线图数据

    返回每日信号统计，用于观察：
    - 综合热度趋势（composite_score 均值）
    - 各维度均值趋势
    - 文章产量趋势（每日多少篇）
    - 来源类型分布变化
    """
    conn = get_database()
    now = datetime.now(timezone.utc)
    date_list = [
        (now - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days - 1, -1, -1)
    ]

    daily_data = []
    for date_str in date_list:
        async with conn.execute("""
            SELECT
                COUNT(*) as article_count,
                AVG(s.composite_score) as avg_composite,
                AVG(s.authority_score) as avg_authority,
                AVG(s.recency_score) as avg_recency,
                AVG(s.content_quality_score) as avg_quality,
                AVG(s.community_score) as avg_community,
                SUM(CASE WHEN s.community_score > 0 THEN 1 ELSE 0 END) as community_count,
                SUM(CASE WHEN s.is_emerging = 1 THEN 1 ELSE 0 END) as emerging_count
            FROM articles_signals s
            JOIN articles a ON s.article_id = a.id
            WHERE s.date = ?
        """, (date_str,)) as cursor:
            row = await cursor.fetchone()
            d = dict(row) if row else {}

        if d and d.get("article_count", 0) > 0:
            daily_data.append({
                "date": date_str,
                "article_count": d["article_count"],
                "avg_composite_score": round(d["avg_composite"] or 0, 3),
                "avg_authority_score": round(d["avg_authority"] or 0, 3),
                "avg_recency_score": round(d["avg_recency"] or 0, 3),
                "avg_content_quality_score": round(d["avg_quality"] or 0, 3),
                "avg_community_score": round(d["avg_community"] or 0, 3),
                "community_coverage_pct": round(
                    (d["community_count"] or 0) / max(d["article_count"], 1), 3
                ),
                "emerging_count": d["emerging_count"] or 0,
            })

    return success_response(data={
        "days": days,
        "daily_trend": daily_data,
        "has_data": len(daily_data) > 0,
    })


@router.get("/top", response_model=dict)
async def get_top_scored_articles(
    days: int = Query(7, ge=1, le=30),
    language: str = Query("mixed"),
    top_k: int = Query(20, ge=1, le=100, description="返回前 N 篇"),
    dimension: Optional[str] = Query(
        None,
        description="按哪个维度排序：composite / authority / recency / quality / community",
    ),
    include_signals: bool = Query(True, description="是否包含完整信号分项"),
):
    """
    高分文章排行 — 前端文章列表

    - 默认按 composite_score 降序
    - 可按 authority/recency/quality/community 维度分别排序
    - 可选包含完整信号分项明细
    """
    conn = get_database()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    date_str = now.strftime("%Y-%m-%d")

    dim_map = {
        "composite": "s.composite_score",
        "authority": "s.authority_score",
        "recency": "s.recency_score",
        "quality": "s.content_quality_score",
        "community": "s.community_score",
    }
    order_col = dim_map.get(dimension, "s.composite_score")

    async with conn.execute(f"""
        SELECT
            s.article_id,
            s.composite_score,
            s.authority_score,
            s.recency_score,
            s.content_quality_score,
            s.community_score,
            s.citation_count,
            s.content_type,
            s.is_emerging,
            s.signal_breakdown,
            a.title,
            a.source,
            a.source_type,
            a.published_at,
            a.url,
            a.summary
        FROM articles_signals s
        JOIN articles a ON s.article_id = a.id
        WHERE s.date = ? AND a.published_at >= ?
        ORDER BY {order_col} DESC
        LIMIT ?
    """, (date_str, since, top_k)) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        # 回退：实时计算
        return await _live_top_articles(conn, days, language, top_k, dimension, include_signals, now, since)

    items = []
    for row in rows:
        d = dict(row)
        breakdown = {}
        try:
            bd_raw = d.get("signal_breakdown")
            if bd_raw:
                breakdown = json.loads(bd_raw) if isinstance(bd_raw, str) else bd_raw
        except Exception:
            pass

        item = {
            "article_id": d["article_id"],
            "title": d["title"][:100] if d["title"] else "",
            "source": d["source"],
            "source_type": d["source_type"],
            "published_at": d["published_at"],
            "url": d["url"],
            "summary": (d["summary"] or "")[:200],
            "composite_score": d["composite_score"],
        }

        if include_signals:
            item.update({
                "authority_score": d["authority_score"],
                "recency_score": d["recency_score"],
                "content_quality_score": d["content_quality_score"],
                "community_score": d["community_score"],
                "citation_count": d["citation_count"] or 0,
                "content_type": d["content_type"],
                "is_emerging": bool(d["is_emerging"]),
                "signal_breakdown": breakdown,
            })

        items.append(item)

    return success_response(data={
        "total": len(items),
        "dimension": dimension or "composite",
        "top_k": top_k,
        "items": items,
    })


@router.get("/sources", response_model=dict)
async def get_source_authority_distribution(
    days: int = Query(7, ge=1, le=30),
):
    """
    来源权威性分布 — 前端来源分析

    返回各来源类型的文章数量和平均权威性分。
    """
    conn = get_database()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    date_str = now.strftime("%Y-%m-%d")

    async with conn.execute("""
        SELECT
            a.source,
            a.source_type,
            COUNT(*) as article_count,
            AVG(s.authority_score) as avg_authority,
            AVG(s.composite_score) as avg_composite,
            MAX(s.composite_score) as max_composite
        FROM articles_signals s
        JOIN articles a ON s.article_id = a.id
        WHERE s.date = ? AND a.published_at >= ?
        GROUP BY a.source, a.source_type
        ORDER BY article_count DESC
    """, (date_str, since)) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return success_response(data={"sources": [], "has_data": False})

    # 按 source_type 汇总
    type_summary: dict = {}
    items = []
    for row in rows:
        d = dict(row)
        items.append({
            "source": d["source"],
            "source_type": d["source_type"],
            "article_count": d["article_count"],
            "avg_authority_score": round(d["avg_authority"] or 0, 3),
            "avg_composite_score": round(d["avg_composite"] or 0, 3),
            "max_composite_score": round(d["max_composite"] or 0, 3),
            "authority_tier": _get_authority_tier(d["avg_authority"] or 0),
        })
        st = d["source_type"]
        if st not in type_summary:
            type_summary[st] = {"count": 0, "total_authority": 0}
        type_summary[st]["count"] += d["article_count"]
        type_summary[st]["total_authority"] += (d["avg_authority"] or 0) * d["article_count"]

    type_distribution = []
    for st, vals in type_summary.items():
        type_distribution.append({
            "source_type": st,
            "article_count": vals["count"],
            "avg_authority_score": round(vals["total_authority"] / max(vals["count"], 1), 3),
            "authority_base": AUTHORITY_BY_TYPE.get(st, 1.0),
        })

    return success_response(data={
        "sources": items,
        "type_distribution": sorted(type_distribution, key=lambda x: x["article_count"], reverse=True),
        "has_data": True,
    })


@router.get("/weights", response_model=dict)
async def get_signal_weights():
    """
    当前信号权重配置 — 前端调参面板

    返回当前的 DEFAULT_WEIGHTS 和各维度说明，
    供前端展示和实验性调参（调参结果仅影响本次计算，不持久化）。
    """
    from services.scoring_engine import DEFAULT_WEIGHTS

    dimension_descriptions = {
        "authority":    "权威性（来源类型 + 子源修正）：官方首发最高 3.0，社区聚合最低 1.0",
        "academic":    "学术性（arXiv 子域 + 引用数 + 代码/数据集）：高引用论文可到 2.5",
        "community":   "社区共鸣（HackerNews 分数/评论归一化）：无 HN 数据则为 0",
        "recency":     "时效性（内容类型半衰期衰减）：官方快讯 6h，论文 48h，深度分析 72h",
        "quality":     "内容质量（摘要长度 + 阅读时长 + 技术词汇密度）：综合得分 0-1",
        "novelty":     "语义新颖性（TF-ICF + 跨簇唯一性）：默认 1.0，ClusteringEngine 更新",
        "controversy":  "争议加成（线性项）：标题/摘要含争议词时生效",
        "breakthrough": "突破加成（线性项）：标题/摘要含突破词时生效",
    }

    return success_response(data={
        "weights": DEFAULT_WEIGHTS,
        "dimension_descriptions": dimension_descriptions,
        "authority_by_type": AUTHORITY_BY_TYPE,
        "content_half-life_hours": CONTENT_HALFLIFE,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────────────────────

async def _compute_and_return_stats(conn, days, language, now, since, date_str):
    """当天无信号数据时，实时计算"""
    query = """
        SELECT a.id, a.title, a.summary, a.source, a.published_at,
               a.url, a.author, a.tags, a.language, a.reading_time_minutes,
               a.source_type, a.external_id
        FROM articles a
        WHERE a.published_at >= ?
    """
    params = [since]
    if language != "mixed":
        query += " AND a.language = ?"
        params.append(language)
    query += " ORDER BY a.published_at DESC"

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return success_response(data={"has_data": False, "message": "无文章数据"})

    articles = []
    for row in rows:
        d = dict(row)
        try:
            tags = json.loads(d.get("tags") or "[]")
        except Exception:
            tags = []
        articles.append({
            "id": d["id"], "title": d["title"], "summary": d.get("summary") or "",
            "source": d["source"], "published_at": d.get("published_at"),
            "url": d["url"], "author": d.get("author"), "tags": tags,
            "language": d.get("language"), "reading_time_minutes": d.get("reading_time_minutes"),
            "source_type": d.get("source_type"), "external_id": d.get("external_id"),
        })

    engine = ScoringEngine()
    scored = engine.score_articles(articles, top_k=len(articles))
    summary = engine.get_signal_summary(scored)

    return success_response(data={
        **_format_stats_response([{"composite_score": a["composite_score"],
                                    "authority_score": a["authority_score"],
                                    "recency_score": a["recency_score"],
                                    "content_quality_score": a["content_quality_score"],
                                    "community_score": a["community_score"],
                                    "is_emerging": a.get("signals") and a["signals"].is_emerging,
                                    "source": a["source"], "source_type": a["source_type"],
                                    "title": a["title"]} for a in scored], date_str, days),
        "live_computed": True,
    })


def _format_stats_response(signals: list[dict], date_str: str, days: int) -> dict:
    """将信号列表格式化为 stats 响应"""
    n = len(signals)
    if n == 0:
        return success_response(data={"has_data": False})

    authority = [s["authority_score"] for s in signals]
    recency = [s["recency_score"] for s in signals]
    quality = [s["content_quality_score"] for s in signals]
    community = [s["community_score"] for s in signals]
    composite = [s["composite_score"] for s in signals]

    # 来源类型分布
    type_counts: dict = {}
    for s in signals:
        st = s.get("source_type", "other")
        type_counts[st] = type_counts.get(st, 0) + 1

    # 高分预览
    top_10 = sorted(signals, key=lambda x: x.get("composite_score", 0), reverse=True)[:10]

    return success_response(data={
        "has_data": True,
        "date": date_str,
        "days": days,
        "total_articles": n,
        "dimension_stats": {
            "authority": _stats_for_list(authority),
            "recency": _stats_for_list(recency),
            "quality": _stats_for_list(quality),
            "community": _stats_for_list(community),
            "composite": _stats_for_list(composite),
        },
        "source_type_distribution": [
            {"source_type": k, "count": v, "pct": round(v / n, 3)}
            for k, v in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        ],
        "top_articles": [
            {
                "article_id": s.get("article_id", ""),
                "title": (s.get("title") or "")[:80],
                "source": s.get("source", ""),
                "composite_score": round(s.get("composite_score", 0), 3),
            }
            for s in top_10
        ],
        "community_coverage_pct": round(len([c for c in community if c > 0]) / n, 3),
        "emerging_count": sum(1 for s in signals if s.get("is_emerging")),
    })


async def _live_top_articles(conn, days, language, top_k, dimension, include_signals, now, since):
    """实时计算高分文章（数据库无信号数据时）"""
    query = """
        SELECT a.id, a.title, a.summary, a.source, a.source_type,
               a.published_at, a.url
        FROM articles a
        WHERE a.published_at >= ?
    """
    params = [since]
    if language != "mixed":
        query += " AND a.language = ?"
        params.append(language)
    query += " ORDER BY a.published_at DESC LIMIT 200"

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return success_response(data={"items": [], "live_computed": True})

    articles = [dict(row) for row in rows]
    engine = ScoringEngine()
    scored = engine.score_articles(articles, top_k=top_k)

    dim_map = {
        "composite": lambda a: a["composite_score"],
        "authority": lambda a: a["authority_score"],
        "recency": lambda a: a["recency_score"],
        "quality": lambda a: a["content_quality_score"],
        "community": lambda a: a["community_score"],
    }
    key_fn = dim_map.get(dimension, lambda a: a["composite_score"])
    scored.sort(key=key_fn, reverse=True)

    items = []
    for a in scored[:top_k]:
        item = {
            "article_id": a.get("id", ""),
            "title": (a.get("title") or "")[:100],
            "source": a.get("source", ""),
            "source_type": a.get("source_type", ""),
            "published_at": a.get("published_at"),
            "url": a.get("url", ""),
            "summary": (a.get("summary") or "")[:200],
            "composite_score": a["composite_score"],
        }
        if include_signals:
            item.update({
                "authority_score": a["authority_score"],
                "recency_score": a["recency_score"],
                "content_quality_score": a["content_quality_score"],
                "community_score": a["community_score"],
                "signal_breakdown": a.get("signals", {}).signal_breakdown if a.get("signals") else {},
            })
        items.append(item)

    return success_response(data={
        "total": len(items),
        "dimension": dimension or "composite",
        "top_k": top_k,
        "items": items,
        "live_computed": True,
    })


async def _save_signals_to_db(conn, scored_articles: list[dict], date_str: str):
    """将计算结果写入 articles_signals 表"""
    now_iso = datetime.now(timezone.utc).isoformat()

    for a in scored_articles:
        signals = a.get("signals")
        if not signals:
            continue

        from services.scoring_engine import ArticleSignals
        if isinstance(signals, ArticleSignals):
            s = signals
        else:
            continue

        breakdown_json = json.dumps(s.signal_breakdown, ensure_ascii=False) if s.signal_breakdown else "{}"

        await conn.execute("""
            INSERT OR REPLACE INTO articles_signals
            (id, article_id, date,
             authority_score, authority_source,
             recency_score, hours_ago,
             content_quality_score, reading_depth_score,
             has_controversy_kw, has_breakthrough_kw,
             engagement_score,
             citation_count, cross_source_mentions,
             composite_score, score_breakdown,
             cluster_id, cluster_topic_label, is_emerging,
             selected_for_top_k, selection_round,
             created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"{a['id']}_{date_str}",
            a["id"],
            date_str,
            s.authority_score,
            s.authority_source,
            s.recency_score,
            s.hours_ago,
            s.content_quality_score,
            s.reading_depth_score,
            int(s.has_controversy_kw),
            int(s.has_breakthrough_kw),
            # articles_signals 旧表使用 engagement_score 列名，语义上对应 community_score
            s.community_score,
            s.citation_count,
            s.cross_source_mentions,
            s.composite_score,
            breakdown_json,
            None,
            None,
            int(s.is_emerging),
            0, 0,
            now_iso,
        ))

    await conn.commit()


def _stats_for_list(values: list[float]) -> dict:
    if not values:
        return {"mean": 0, "min": 0, "max": 0, "p50": 0, "p90": 0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "mean": round(sum(sorted_vals) / n, 3),
        "min": round(min(sorted_vals), 3),
        "max": round(max(sorted_vals), 3),
        "p50": round(sorted_vals[n // 2], 3),
        "p90": round(sorted_vals[int(n * 0.9)], 3),
    }


def _get_authority_tier(avg_score: float) -> str:
    if avg_score >= 2.5:
        return "S"
    elif avg_score >= 2.0:
        return "A"
    elif avg_score >= 1.5:
        return "B"
    elif avg_score >= 1.0:
        return "C"
    return "D"
