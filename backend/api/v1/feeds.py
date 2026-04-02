from fastapi import APIRouter

from models.article import FeedCreate, CrawlResult
from core.database import get_database
from core.responses import success_response, error_response

router = APIRouter(prefix="/feeds", tags=["Feeds"])


def _row_to_feed(row) -> dict:
    d = dict(row)
    return {
        "id": d["id"],
        "name": d["name"],
        "url": d["url"],
        "source": d["source"],
        "source_url": d.get("source_url"),
        "category": d["category"],
        "enabled": bool(d["enabled"]),
        "description": d.get("description"),
        "favicon_url": d.get("favicon_url"),
        "language": d.get("language"),
        "last_fetched_at": d.get("last_fetched_at"),
        "article_count": d.get("article_count", 0),
        "created_at": d.get("created_at"),
    }


@router.get("/", response_model=dict)
async def list_feeds():
    """List all RSS feeds."""
    conn = get_database()
    feeds = []
    async with conn.execute("SELECT * FROM feeds ORDER BY name") as cursor:
        async for row in cursor:
            feeds.append(_row_to_feed(row))
    return success_response(data=feeds)


@router.post("/", response_model=dict)
async def create_feed(feed: FeedCreate):
    """Add a new RSS feed."""
    from services.rss_crawler import RSSCrawler
    crawler = RSSCrawler()
    feed_id = await crawler.add_feed(feed)
    await crawler.close()
    return success_response(data={"id": feed_id, "message": "Feed added successfully"})


@router.delete("/{feed_id}", response_model=dict)
async def delete_feed(feed_id: str):
    """Delete an RSS feed."""
    conn = get_database()
    async with conn.execute("SELECT id FROM feeds WHERE id = ?", (feed_id,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        return error_response(message="Feed not found", code=404)
    await conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    await conn.commit()
    return success_response(message="Feed deleted successfully")


@router.get("/{feed_id}/crawl", response_model=dict)
async def crawl_feed(
    feed_id: str,
    force: bool = False,
    fetch_content: bool = False,
    days: int | None = 7,
):
    """
    Manually crawl a specific RSS feed.

    - `force`: re-fetch articles even if they already exist (by URL)
    - `fetch_content`: also fetch full article HTML bodies (slower, more data)
    """
    from services.rss_crawler import RSSCrawler
    crawler = RSSCrawler()
    result = await crawler.crawl_specific_feed(feed_id, force=force, fetch_content=fetch_content, days=days)
    await crawler.close()
    if not result:
        return error_response(message="Feed not found", code=404)
    return success_response(data=result.model_dump())


@router.post("/crawl-all", response_model=dict)
async def crawl_all_feeds(force: bool = False, fetch_content: bool = False, days: int | None = 7):
    """
    Crawl all enabled RSS feeds.

    - `force`: re-fetch articles even if they already exist (by URL)
    - `fetch_content`: also fetch full article HTML bodies (slower, more data)
    """
    from services.rss_crawler import RSSCrawler
    crawler = RSSCrawler()
    results = await crawler.crawl_all_feeds(force=force, fetch_content=fetch_content, days=days)
    await crawler.close()
    total_fetched = sum(r.articles_fetched for r in results)
    total_saved = sum(r.articles_saved for r in results)
    return success_response(data={
        "results": [r.model_dump() for r in results],
        "summary": {
            "total_feeds": len(results),
            "total_articles_fetched": total_fetched,
            "total_articles_saved": total_saved,
        }
    })


@router.post("/seed-default", response_model=dict)
async def seed_default_feeds(reset: bool = False):
    """
    Seed the database with default AI RSS feeds.
    - `reset=True`: delete all existing feeds first, then re-seed (recommended after updating DEFAULT_FEEDS)
    - `reset=False` (default): skip feeds that already exist
    """
    from services.rss_crawler import RSSCrawler
    crawler = RSSCrawler()
    result = await crawler.seed_default_feeds(reset=reset)
    await crawler.close()
    return success_response(data={
        **result,
        "message": f"Feeds {'reset and seeded' if reset else 'seeded'} successfully",
    })
