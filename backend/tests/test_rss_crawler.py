import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import hashlib

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.rss_crawler import RSSCrawler
from models.article import FeedCreate, CrawlResult


class MockDatabase:
    """Mock database for testing."""

    def __init__(self):
        self.feeds = MockCollection()
        self.articles = MockCollection()


class MockCollection:
    """Mock MongoDB collection."""

    def __init__(self):
        self._data = {}
        self._counter = 0

    async def find_one(self, query):
        key = query.get("_id") or query.get("url")
        return self._data.get(key)

    async def find(self, query=None, **kwargs):
        results = []
        for doc in self._data.values():
            if query:
                match = True
                for k, v in query.items():
                    if doc.get(k) != v:
                        match = False
                        break
                if match:
                    results.append(doc)
            else:
                results.append(doc)
        return MockCursor(results)

    async def insert_one(self, doc):
        self._counter += 1
        key = doc.get("_id") or str(self._counter)
        self._data[key] = doc
        result = MagicMock()
        result.inserted_id = key
        return result

    async def update_one(self, query, update, upsert=False):
        key = query.get("_id")
        if key in self._data:
            if "$set" in update:
                self._data[key].update(update["$set"])
            if "$inc" in update:
                for k, v in update["$inc"].items():
                    self._data[key][k] = self._data[key].get(k, 0) + v
            if "$setOnInsert" in update:
                self._data[key].update(update["$setOnInsert"])
        elif upsert:
            self._data[key] = {}
            if "$setOnInsert" in update:
                self._data[key].update(update["$setOnInsert"])
        result = MagicMock()
        result.modified_count = 1
        result.upserted_id = key if upsert else None
        return result

    async def delete_one(self, query):
        key = query.get("_id")
        if key in self._data:
            del self._data[key]
        result = MagicMock()
        result.deleted_count = 1 if key in self._data else 0
        return result


class MockCursor:
    """Mock async cursor."""

    def __init__(self, data):
        self._data = data
        self._index = 0

    def sort(self, field, direction=1):
        self._data.sort(key=lambda x: x.get(field, ""), reverse=(direction == -1))
        return self

    def skip(self, n):
        self._data = self._data[n:]
        return self

    def limit(self, n):
        self._data = self._data[:n]
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._data):
            raise StopAsyncIteration
        result = self._data[self._index]
        self._index += 1
        return result


class TestRSSCrawlerUnit:
    """Unit tests for RSSCrawler (no network required)."""

    def setup_method(self):
        self.db = MockDatabase()
        self.crawler = RSSCrawler(self.db)

    def test_generate_article_id(self):
        url = "https://example.com/article-123"
        id1 = self.crawler._generate_article_id(url)
        id2 = self.crawler._generate_article_id(url)
        # Same URL should produce same ID
        assert id1 == id2
        # Should be a valid MD5 hex digest (32 chars)
        assert len(id1) == 32
        assert id1 == hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()

    def test_generate_article_id_different_urls(self):
        url1 = "https://example.com/article-1"
        url2 = "https://example.com/article-2"
        id1 = self.crawler._generate_article_id(url1)
        id2 = self.crawler._generate_article_id(url2)
        assert id1 != id2

    def test_parse_date_valid(self):
        from dateutil.parser import parse as date_parse
        result = self.crawler._parse_date("2025-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15
        assert result.tzinfo is not None

    def test_parse_date_invalid(self):
        result = self.crawler._parse_date("not-a-date")
        assert result is None

    def test_parse_date_none(self):
        result = self.crawler._parse_date(None)
        assert result is None

    def test_parse_date_empty(self):
        result = self.crawler._parse_date("")
        assert result is None

    def test_extract_summary_with_summary_field(self):
        entry = {"summary": "<p>This is a <b>test</b> article with HTML.</p>"}
        result = self.crawler._extract_summary(entry)
        assert result is not None
        assert "test" in result
        assert "<" not in result  # HTML stripped

    def test_extract_summary_with_description(self):
        entry = {"description": "A simple description without HTML."}
        result = self.crawler._extract_summary(entry)
        assert result == "A simple description without HTML."

    def test_extract_summary_empty(self):
        entry = {}
        result = self.crawler._extract_summary(entry)
        assert result is None

    def test_extract_summary_long_text_truncated(self):
        long_text = "A" * 600
        entry = {"summary": long_text}
        result = self.crawler._extract_summary(entry)
        assert result is not None
        assert len(result) <= 500
        assert result.endswith("...")

    def test_extract_tags_from_tags_field(self):
        entry = {"tags": [{"term": "AI"}, {"term": "ML"}]}
        result = self.crawler._extract_tags(entry)
        assert set(result) == {"AI", "ML"}

    def test_extract_tags_from_category(self):
        entry = {"category": "Research"}
        result = self.crawler._extract_tags(entry)
        assert "Research" in result

    def test_extract_tags_deduplicated(self):
        entry = {"tags": [{"term": "AI"}], "category": "AI"}
        result = self.crawler._extract_tags(entry)
        assert result.count("AI") == 1

    def test_extract_tags_empty(self):
        entry = {}
        result = self.crawler._extract_tags(entry)
        assert result == []

    def test_default_feeds_populated(self):
        feeds = RSSCrawler.DEFAULT_FEEDS
        assert len(feeds) > 0
        # All feeds should have required fields
        for feed in feeds:
            assert "name" in feed
            assert "url" in feed
            assert "source" in feed
            assert feed["url"].startswith("http")

    def test_crawl_feed_no_id_returns_error(self):
        feed = {"name": "Test Feed", "url": "https://example.com/feed.xml"}
        result = self.crawler.crawl_feed(feed)
        assert result.articles_fetched == 0
        assert result.articles_saved == 0
        assert len(result.errors) > 0
        assert "no ID" in result.errors[0]


class TestRSSCrawlerAsync:
    """Async tests for RSSCrawler with mocked network."""

    def setup_method(self):
        self.db = MockDatabase()
        self.crawler = RSSCrawler(self.db)

    @pytest.mark.asyncio
    async def test_add_feed(self):
        feed_data = FeedCreate(
            name="Test Feed",
            url="https://test.com/feed.xml",
            source="Test",
            category="Test",
        )
        feed_id = await self.crawler.add_feed(feed_data)
        assert feed_id == "https://test.com/feed.xml"

        # Verify it was stored
        stored = await self.db.feeds.find_one({"_id": feed_id})
        assert stored is not None
        assert stored["name"] == "Test Feed"
        assert stored["article_count"] == 0

    @pytest.mark.asyncio
    async def test_add_duplicate_feed_updates(self):
        feed_data = FeedCreate(
            name="Test Feed",
            url="https://test.com/feed.xml",
            source="Test",
            category="Test",
        )
        await self.crawler.add_feed(feed_data)

        # Add same feed again with different name
        feed_data2 = FeedCreate(
            name="Updated Feed Name",
            url="https://test.com/feed.xml",
            source="Test",
            category="Test",
        )
        await self.crawler.add_feed(feed_data2)

        # Should update, not duplicate
        stored = await self.db.feeds.find_one({"_id": "https://test.com/feed.xml"})
        assert stored["name"] == "Updated Feed Name"

    @pytest.mark.asyncio
    async def test_seed_default_feeds(self):
        count = await self.crawler.seed_default_feeds()
        assert count == len(RSSCrawler.DEFAULT_FEEDS)

        # Verify all feeds were added
        cursor = self.db.feeds.find()
        stored_feeds = []
        async for feed in cursor:
            stored_feeds.append(feed)
        assert len(stored_feeds) == len(RSSCrawler.DEFAULT_FEEDS)

    @pytest.mark.asyncio
    async def test_crawl_specific_feed_not_found(self):
        result = await self.crawler.crawl_specific_feed("nonexistent-feed-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_crawl_specific_feed_fetch_error(self):
        # Add a feed
        feed_data = FeedCreate(
            name="Test Feed",
            url="https://invalid-url-that-will-fail.com/feed.xml",
            source="Test",
            category="Test",
        )
        await self.crawler.add_feed(feed_data)

        result = await self.crawler.crawl_specific_feed("https://invalid-url-that-will-fail.com/feed.xml")
        assert result is not None
        assert result.articles_fetched == 0
        assert result.articles_saved == 0
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_crawl_all_feeds_empty(self):
        results = await self.crawler.crawl_all_feeds()
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_crawl_all_feeds_with_enabled_feeds(self):
        # Add two feeds
        await self.crawler.add_feed(FeedCreate(
            name="Feed 1", url="https://feed1.com/rss", source="Source1", category="AI"
        ))
        await self.crawler.add_feed(FeedCreate(
            name="Feed 2", url="https://feed2.com/rss", source="Source2", category="AI"
        ))

        # Disable one
        await self.db.feeds.update_one(
            {"_id": "https://feed2.com/rss"},
            {"$set": {"enabled": False}}
        )

        results = await self.crawler.crawl_all_feeds()
        assert len(results) == 1
        assert results[0].feed_name == "Feed 1"
