"""
Pydantic models for hn_metadata table.

Covers: Hacker News AI / Hacker News ML / HN Front Page
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class HNContentType(str, Enum):
    LINK = "link"
    ASK_HN = "ask_hn"
    SHOW_HN = "show_hn"
    POLL = "poll"


class HNMetadataBase(BaseModel):
    """Base fields shared by create and response models."""
    hn_id: int = Field(..., description="HN story ID, e.g. 12345678")
    hn_url: str = Field(..., description="HN discussion URL: https://news.ycombinator.com/item?id=xxx")
    hn_author: str = Field(..., description="HN username who submitted the post")
    hn_author_karma: int = Field(default=0, description="HN karma of the submitter")
    hn_score: int = Field(default=0, description="HN upvote score")
    hn_descendants: int = Field(default=0, description="Total comment count including sub-comments")
    hn_comments: int = Field(default=0, description="Top-level comment count only")
    hn_rank: Optional[int] = Field(None, description="Rank in HN Top-30 (daily snapshot)")
    content_type: HNContentType = Field(default=HNContentType.LINK, description="Post type")
    is_ask_hn: bool = Field(default=False, description="True if this is an Ask HN post")
    is_show_hn: bool = Field(default=False, description="True if this is a Show HN post")
    is_poll: bool = Field(default=False, description="True if this is a Poll post")
    linked_github_repo: Optional[str] = Field(None, description="GitHub repo if linked: 'owner/repo'")
    linked_arxiv_id: Optional[str] = Field(None, description="arXiv ID if linked: '2404.12345'")
    linked_domain: Optional[str] = Field(None, description="Domain of the external link")
    sentiment_proxy: Optional[str] = Field(None, description="LLM-synthesised from comments: positive/negative/controversial/neutral")
    top_comment_preview: Optional[str] = Field(None, description="Preview of the top-voted comment (first 200 chars)")
    score_peak: int = Field(default=0, description="Historical peak score")
    score_peak_at: Optional[datetime] = Field(None, description="When the peak score was reached")
    velocity_score: float = Field(default=0.0, description="Velocity: (current - yesterday) / yesterday")


class HNMetadataCreate(HNMetadataBase):
    """Model used when writing a new hn_metadata record."""
    article_id: str


class HNMetadataInDB(HNMetadataBase):
    """Model for an hn_metadata record read from the database."""
    id: str
    article_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class HNMetadataResponse(HNMetadataBase):
    """API response for hn_metadata."""
    id: str
    article_id: str
    created_at: datetime
