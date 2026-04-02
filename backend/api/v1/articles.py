from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
import json

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
    start_date: Optional[datetime] = Query(None, description="Filter articles from this date"),
    end_date: Optional[datetime] = Query(None, description="Filter articles until this date"),
    language: Optional[str] = Query(None, description="Filter by language: en / zh / mixed"),
    has_content: Optional[bool] = Query(None, description="Filter articles with full content fetched"),
):
    """List articles with pagination and filtering."""
    conn = get_database()
    conditions = []
    params = []

    if source:
        conditions.append("source = ?")
        params.append(source)
    if feed_id:
        conditions.append("feed_id = ?")
        params.append(feed_id)
    if keyword:
        conditions.append("(title LIKE ? OR summary LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if start_date:
        conditions.append("published_at >= ?")
        params.append(start_date.isoformat())
    if end_date:
        conditions.append("published_at <= ?")
        params.append(end_date.isoformat())
    if language:
        conditions.append("language = ?")
        params.append(language)
    if has_content is not None:
        conditions.append("content_fetched = ?")
        params.append(1 if has_content else 0)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    async with conn.execute(f"SELECT COUNT(*) as cnt FROM articles {where_clause}", params) as cursor:
        row = await cursor.fetchone()
        total = row["cnt"]

    pages = (total + page_size - 1) // page_size if total > 0 else 1
    offset = (page - 1) * page_size

    async with conn.execute(
        f"SELECT * FROM articles {where_clause} ORDER BY published_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset]
    ) as cursor:
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
