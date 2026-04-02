from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ArticleBase(BaseModel):
    """Base article model with common fields."""
    title: str = Field(..., description="Article title")
    url: str = Field(..., description="Original article URL")
    source: str = Field(..., description="Source name (e.g., arXiv, Hugging Face)")
    source_url: Optional[str] = Field(None, description="Source homepage URL")
    author: Optional[str] = Field(None, description="Article author(s)")
    published_at: Optional[datetime] = Field(None, description="Publication datetime")
    summary: Optional[str] = Field(None, max_length=1000, description="Article summary/abstract")
    content: Optional[str] = Field(None, description="Full article content")
    tags: list[str] = Field(default_factory=list, description="Tags/categories")
    image_url: Optional[str] = Field(None, description="Article cover image URL")
    language: Optional[str] = Field(None, description="Language code: en / zh / mixed")
    reading_time_minutes: Optional[int] = Field(None, description="Estimated reading time in minutes")


class ArticleCreate(ArticleBase):
    """Model for creating a new article during crawl."""
    feed_id: str = Field(..., description="RSS feed ID this article came from")
    external_id: Optional[str] = Field(None, description="Original GUID/ID from source feed")
    content_hash: Optional[str] = Field(None, description="MD5 hash of content for deduplication")
    content_fetched: bool = Field(default=False, description="Whether full content was fetched")
    fetched_at: datetime = Field(default_factory=datetime.utcnow, description="When this article was fetched")


class ArticleInDB(ArticleBase):
    """Model representing an article stored in the database."""
    id: str
    external_id: Optional[str] = None
    feed_id: str
    content_hash: Optional[str] = None
    content_fetched: bool = False
    fetched_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class ArticleResponse(ArticleBase):
    """API response model for an article."""
    id: str = Field(..., description="Article ID")
    feed_id: str
    external_id: Optional[str] = None
    content_hash: Optional[str] = None
    content_fetched: bool = False
    reading_time_minutes: Optional[int] = None
    fetched_at: datetime
    created_at: datetime


class FeedBase(BaseModel):
    """Base RSS feed model."""
    name: str = Field(..., description="Feed name")
    url: str = Field(..., description="RSS feed URL")
    source: str = Field(..., description="Source name")
    source_url: Optional[str] = Field(None, description="Source homepage URL")
    category: str = Field(default="AI", description="Feed category")
    enabled: bool = Field(default=True, description="Whether this feed is active")
    description: Optional[str] = Field(None, description="Feed description")
    favicon_url: Optional[str] = Field(None, description="Feed/site favicon URL")
    language: Optional[str] = Field(None, description="Primary language of this feed")


class FeedCreate(FeedBase):
    """Model for creating a new RSS feed."""
    pass


class FeedInDB(FeedBase):
    """Model representing a feed stored in the database."""
    id: str
    last_fetched_at: Optional[datetime] = None
    article_count: int = Field(default=0, description="Total articles fetched from this feed")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class FeedResponse(FeedBase):
    """API response model for a feed."""
    id: str
    last_fetched_at: Optional[datetime] = None
    article_count: int = 0
    created_at: datetime


class CrawlResult(BaseModel):
    """Result of a crawl operation."""
    feed_id: str
    feed_name: str
    articles_fetched: int
    articles_saved: int
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float


class ArticleListResponse(BaseModel):
    """Paginated article list response."""
    items: list[ArticleResponse]
    total: int
    page: int
    page_size: int
    pages: int
