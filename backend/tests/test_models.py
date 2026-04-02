import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from models.article import (
    ArticleCreate,
    FeedCreate,
    CrawlResult,
    ArticleResponse,
    FeedResponse,
    ArticleListResponse,
)


class TestArticleModels:
    """Test Pydantic models for articles."""

    def test_article_create_valid(self):
        article = ArticleCreate(
            title="Test Article",
            url="https://example.com/article",
            source="Test Source",
            feed_id="test-feed-001",
        )
        assert article.title == "Test Article"
        assert article.url == "https://example.com/article"
        assert article.source == "Test Source"
        assert article.feed_id == "test-feed-001"
        assert article.summary is None
        assert article.tags == []

    def test_article_create_with_all_fields(self):
        now = datetime.now(timezone.utc)
        article = ArticleCreate(
            title="AI Breakthrough",
            url="https://example.com/ai-breakthrough",
            source="AI News",
            feed_id="feed-001",
            source_url="https://example.com",
            published_at=now,
            summary="A summary of the article.",
            content="Full article content here.",
            tags=["AI", "ML", "Research"],
        )
        assert article.title == "AI Breakthrough"
        assert article.published_at == now
        assert article.summary == "A summary of the article."
        assert len(article.tags) == 3
        assert "AI" in article.tags

    def test_article_create_defaults(self):
        article = ArticleCreate(
            title="Minimal Article",
            url="https://example.com/minimal",
            source="Source",
            feed_id="feed-001",
        )
        assert article.tags == []
        assert article.published_at is None
        assert article.summary is None
        assert article.content is None

    def test_article_create_missing_required(self):
        with pytest.raises(TypeError):
            ArticleCreate(title="Only Title")

    def test_crawl_result_model(self):
        result = CrawlResult(
            feed_id="feed-001",
            feed_name="Test Feed",
            articles_fetched=10,
            articles_saved=8,
            errors=["Error 1"],
            duration_seconds=1.5,
        )
        assert result.articles_fetched == 10
        assert result.articles_saved == 8
        assert len(result.errors) == 1
        assert result.errors[0] == "Error 1"
        assert result.duration_seconds == 1.5

    def test_crawl_result_defaults(self):
        result = CrawlResult(
            feed_id="feed-001",
            feed_name="Test Feed",
            articles_fetched=5,
            articles_saved=5,
        )
        assert result.errors == []
        assert result.duration_seconds == 0.0

    def test_feed_create_model(self):
        feed = FeedCreate(
            name="Test Feed",
            url="https://example.com/feed.xml",
            source="Test Source",
            category="AI",
        )
        assert feed.name == "Test Feed"
        assert feed.enabled is True
        assert feed.description is None

    def test_feed_create_full(self):
        feed = FeedCreate(
            name="Hugging Face Blog",
            url="https://huggingface.co/blog/feed.xml",
            source="Hugging Face",
            source_url="https://huggingface.co",
            category="AI",
            description="HF blog posts",
        )
        assert feed.name == "Hugging Face Blog"
        assert feed.enabled is True
        assert feed.category == "AI"
