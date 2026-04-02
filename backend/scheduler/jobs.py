import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.config import get_settings
from services.rss_crawler import RSSCrawler

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def crawl_all_feeds_job():
    """Scheduled job to crawl all RSS feeds (last 7 days by default)."""
    logger.info("Starting scheduled RSS crawl...")
    try:
        crawler = RSSCrawler()
        results = await crawler.crawl_all_feeds(days=7)
        await crawler.close()

        total_fetched = sum(r.articles_fetched for r in results)
        total_saved = sum(r.articles_saved for r in results)
        logger.info(
            f"Scheduled crawl completed: {len(results)} feeds, "
            f"{total_fetched} articles fetched, {total_saved} saved."
        )
    except Exception as e:
        logger.error(f"Scheduled crawl failed: {e}")


def start_scheduler():
    """Start the APScheduler."""
    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler is disabled in settings.")
        return

    interval_minutes = settings.CRAWL_INTERVAL_MINUTES
    scheduler.add_job(
        crawl_all_feeds_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="rss_crawl_job",
        name="RSS Feed Crawler",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started. Crawl interval: every {interval_minutes} minutes.")


def stop_scheduler():
    """Stop the APScheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")
