from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
import json
from dateutil import parser as dateparser

from core.database import get_database, db as global_db
from core.responses import success_response, error_response

router = APIRouter(prefix="/articles", tags=["Articles"])


def _row_to_article(row) -> dict:
    d = dict(row)
    tags = d.get("tags", "[]")
    try:
        tags = json.loads(tags) if isinstance(tags, str) else tags
    except Exception:
        tags = []
    return {
        "id": d["id"],
        "external_id": d.get("external_id"),
        "title": d["title"],
        "url": d["url"],
        "source": d["source"],
        "source_url": d.get("source_url"),
        "author": d.get("author"),
        "published_at": d.get("published_at"),
        "summary": d.get("summary"),
        "content": d.get("content"),
        "content_hash": d.get("content_hash"),
        "image_url": d.get("image_url"),
        "language": d.get("language"),
        "reading_time_minutes": d.get("reading_time_minutes"),
        "tags": tags,
        "feed_id": d["feed_id"],
        "content_fetched": bool(d.get("content_fetched", 0)),
        "fetched_at": d.get("fetched_at"),
        "created_at": d.get("created_at"),
    }


@router.get("/", response_model=dict)
async def list_articles(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    source: Optional[str] = Query(None, description="Filter by source"),
    feed_id: Optional[str] = Query(None, description="Filter by feed ID"),
    keyword: Optional[str] = Query(None, description="Search in title/summary"),
    start_date: Optional[str] = Query(None, description="Filter articles from this date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filter articles until this date (YYYY-MM-DD)"),
    language: Optional[str] = Query(None, description="Filter by language: en / zh / mixed"),
    has_content: Optional[bool] = Query(None, description="Filter articles with full content fetched"),
    include_signals: bool = Query(
        False,
        description="Join with articles_signals table to include signal scores",
    ),
    signal_date: Optional[str] = Query(
        None,
        description="Signal date (YYYY-MM-DD). Defaults to today. Only used when include_signals=True",
    ),
):
    """
    List articles with pagination and filtering.

    When include_signals=True, joins with articles_signals table and returns
    composite_score, authority_score, recency_score, content_quality_score, and
    community_score for each article.
    """
    from datetime import datetime as dt
    conn = get_database()
    conditions = []
    params = []
    offset = (page - 1) * page_size

    if source:
        conditions.append("a.source = ?")
        params.append(source)
    if feed_id:
        conditions.append("a.feed_id = ?")
        params.append(feed_id)
    if keyword:
        conditions.append("(a.title LIKE ? OR a.summary LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    # parse date strings safely
    def _parse_date(val: Optional[str]) -> Optional[str]:
        if not val:
            return None
        try:
            return dateparser.parse(val).isoformat()
        except Exception:
            return None

    start_iso = _parse_date(start_date)
    end_iso = _parse_date(end_date)

    if start_iso:
        conditions.append("a.published_at >= ?")
        params.append(start_iso)
    if end_iso:
        conditions.append("a.published_at <= ?")
        params.append(end_iso)
    if language:
        conditions.append("a.language = ?")
        params.append(language)
    if has_content is not None:
        conditions.append("a.content_fetched = ?")
        params.append(1 if has_content else 0)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    if include_signals:
        sig_date = signal_date or dt.now(timezone.utc).strftime("%Y-%m-%d")
        # Keep articles as the driving table; signal fields are optional.
        # Do not put s.date in WHERE, otherwise LEFT JOIN degrades to INNER JOIN.
        signal_where = where_clause

        count_sql = f"""
            SELECT COUNT(*) as cnt
            FROM articles a
            {where_clause}
        """
        list_sql = f"""
            SELECT
                a.*,
                s.composite_score,
                s.authority_score,
                s.recency_score,
                s.content_quality_score,
                s.engagement_score AS community_score,
                s.citation_count,
                NULL AS content_type,
                s.score_breakdown AS signal_breakdown
            FROM articles a
            LEFT JOIN articles_signals s ON a.id = s.article_id AND s.date = ?
            {signal_where}
            ORDER BY s.composite_score DESC, a.published_at DESC
            LIMIT ? OFFSET ?
        """
        count_params = params
        list_params = [sig_date] + params + [page_size, offset]
    else:
        count_sql = f"SELECT COUNT(*) as cnt FROM articles a {where_clause}"
        count_params = params
        list_sql = f"""
            SELECT a.* FROM articles a
            {where_clause}
            ORDER BY a.published_at DESC
            LIMIT ? OFFSET ?
        """
        list_params = params + [page_size, offset]

    async with conn.execute(count_sql, count_params) as cursor:
        row = await cursor.fetchone()
        total = row["cnt"]

    pages = (total + page_size - 1) // page_size if total > 0 else 1

    if include_signals:
        async with conn.execute(list_sql, list_params) as cursor:
            rows = await cursor.fetchall()
        articles = []
        for row in rows:
            d = _row_to_article(row)
            if row["composite_score"] is not None:
                d["composite_score"] = row["composite_score"]
                d["authority_score"] = row["authority_score"]
                d["recency_score"] = row["recency_score"]
                d["content_quality_score"] = row["content_quality_score"]
                d["community_score"] = row["community_score"]
                d["citation_count"] = row["citation_count"]
                d["content_type"] = row["content_type"]
                try:
                    bd = row["signal_breakdown"]
                    d["signal_breakdown"] = json.loads(bd) if bd else {}
                except Exception:
                    d["signal_breakdown"] = {}
            else:
                d["composite_score"] = None
            articles.append(d)
    else:
        async with conn.execute(list_sql, list_params) as cursor:
            rows = await cursor.fetchall()
        articles = [_row_to_article(row) for row in rows]

    return success_response(data={
        "items": articles,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    })


@router.get("/search", response_model=dict)
async def search_articles(
    q: str = Query(..., min_length=1, description="Full-text search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
):
    """
    Full-text search using SQLite FTS5.
    Supports FTS5 query syntax: quotes for phrases, AND/OR operators, wildcards.
    """
    if not q or not q.strip():
        return error_response(message="Query cannot be empty", code=400)

    try:
        article_ids = await global_db.fts_search(q.strip(), limit=limit)
    except Exception as e:
        return error_response(message=f"Search failed: {e}", code=500)

    if not article_ids:
        return success_response(data={"items": [], "total": 0})

    conn = get_database()
    articles = []
    placeholders = ",".join("?" * len(article_ids))
    async with conn.execute(
        f"SELECT * FROM articles WHERE id IN ({placeholders}) ORDER BY published_at DESC",
        article_ids
    ) as cursor:
        async for row in cursor:
            articles.append(_row_to_article(row))

    return success_response(data={"items": articles, "total": len(articles)})


@router.get("/{article_id}", response_model=dict)
async def get_article(article_id: str):
    """Get a specific article by ID."""
    conn = get_database()
    async with conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        return error_response(message="Article not found", code=404)
    return success_response(data=_row_to_article(row))


@router.delete("/{article_id}", response_model=dict)
async def delete_article(article_id: str):
    """Delete an article."""
    conn = get_database()
    async with conn.execute("SELECT id FROM articles WHERE id = ?", (article_id,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        return error_response(message="Article not found", code=404)
    await conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    await conn.execute("DELETE FROM article_fts WHERE article_id = ?", (article_id,))
    await conn.commit()
    return success_response(message="Article deleted successfully")


@router.get("/stats/overview", response_model=dict)
async def get_stats():
    """Get article statistics."""
    conn = get_database()

    async with conn.execute("SELECT COUNT(*) as cnt FROM articles") as cursor:
        row = await cursor.fetchone()
        total_articles = row["cnt"]

    async with conn.execute("SELECT COUNT(*) as cnt FROM articles WHERE content_fetched = 1") as cursor:
        row = await cursor.fetchone()
        articles_with_content = row["cnt"]

    # Count by source
    source_counts = []
    async with conn.execute(
        "SELECT source, COUNT(*) as cnt FROM articles GROUP BY source ORDER BY cnt DESC"
    ) as cursor:
        async for row in cursor:
            source_counts.append({"source": row["source"], "count": row["cnt"]})

    # Count by language
    lang_counts = []
    async with conn.execute(
        "SELECT language, COUNT(*) as cnt FROM articles WHERE language IS NOT NULL GROUP BY language ORDER BY cnt DESC"
    ) as cursor:
        async for row in cursor:
            lang_counts.append({"language": row["language"], "count": row["cnt"]})

    # Recent articles (last 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    async with conn.execute(
        "SELECT COUNT(*) as cnt FROM articles WHERE published_at >= ?", (week_ago.isoformat(),)
    ) as cursor:
        row = await cursor.fetchone()
        recent_count = row["cnt"]

    return success_response(data={
        "total_articles": total_articles,
        "articles_with_content": articles_with_content,
        "recent_articles_7d": recent_count,
        "by_source": source_counts,
        "by_language": lang_counts,
    })


@router.delete("/", response_model=dict)
async def delete_articles(
    before_date: Optional[datetime] = Query(None, description="Delete articles before this date"),
    source: Optional[str] = Query(None, description="Delete articles from this source"),
    feed_id: Optional[str] = Query(None, description="Delete articles from this feed"),
):
    """Batch delete articles with filters."""
    conn = get_database()
    conditions = []
    params = []
    if before_date:
        conditions.append("published_at < ?")
        params.append(before_date.isoformat())
    if source:
        conditions.append("source = ?")
        params.append(source)
    if feed_id:
        conditions.append("feed_id = ?")
        params.append(feed_id)
    if not conditions:
        return error_response(message="At least one filter is required", code=400)

    where_clause = "WHERE " + " AND ".join(conditions)
    async with conn.execute(f"DELETE FROM articles {where_clause}", params) as cursor:
        deleted = cursor.rowcount
    await conn.commit()
    return success_response(data={"deleted_count": deleted})
