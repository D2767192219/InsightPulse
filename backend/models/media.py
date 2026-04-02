"""
Pydantic models for media_metadata and official_metadata tables.

media_metadata covers: TechCrunch / MIT Technology Review / VentureBeat /
    The Verge / SiliconANGLE / AI News / MarkTechPost / Inside AI News

official_metadata covers: OpenAI / DeepMind / NVIDIA / AWS / The Gradient /
    Synced Review / InfoQ / Nature
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Media Metadata ─────────────────────────────────────────────────────────────

class MediaArticleType(str, Enum):
    NEWS = "news"
    OPINION = "opinion"
    ANALYSIS = "analysis"
    INTERVIEW = "interview"
    REVIEW = "review"


class MediaMetadataBase(BaseModel):
    """Base fields shared by create and response models for media_metadata."""
    publisher: Optional[str] = Field(None, description='Full publisher name, e.g. "Vox Media"')
    section: Optional[str] = Field(None, description='Section, e.g. "AI" / "Enterprise" / "Startups"')
    article_type: MediaArticleType = Field(default=MediaArticleType.NEWS, description="Article genre")
    mentioned_companies: list[str] = Field(default_factory=list, description='Companies mentioned, e.g. ["OpenAI", "Google"]')
    mentioned_products: list[str] = Field(default_factory=list, description='Products mentioned, e.g. ["GPT-4o", "Gemini"]')
    mentioned_persons: list[str] = Field(default_factory=list, description='People mentioned, e.g. ["Sam Altman"]')
    mentioned_models: list[str] = Field(default_factory=list, description='AI models mentioned, e.g. ["GPT-4", "Llama-3"]')
    is_funding_news: bool = Field(default=False, description="Financing / investment news")
    is_acquisition_news: bool = Field(default=False, description="Acquisition news")
    is_regulation_news: bool = Field(default=False, description="Regulation / policy news")
    is_product_launch: bool = Field(default=False, description="Product launch news")
    funding_amount: Optional[str] = Field(None, description='Funding amount, e.g. "$1.3B"')
    funding_round: Optional[str] = Field(None, description='Funding round, e.g. "Series C"')
    acquiring_company: Optional[str] = Field(None, description="Acquiring company name")
    regulation_region: Optional[str] = Field(None, description="Region involved in regulation, e.g. 'EU' / 'US' / 'China'")
    sentiment_label: Optional[str] = Field(None, description="LLM sentiment: positive/negative/neutral/controversial")
    sentiment_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Sentiment confidence score")
    has_controversy: bool = Field(default=False, description="Article involves controversy")
    cites_arxiv_ids: list[str] = Field(default_factory=list, description="arXiv IDs cited in the article")
    cites_hn_ids: list[int] = Field(default_factory=list, description="HN story IDs cited")
    cites_press_releases: list[str] = Field(default_factory=list, description="Official press release titles cited")
    is_original_report: bool = Field(default=False, description="Original reporting by site journalist")
    is_syndicated: bool = Field(default=False, description="Reprinted / syndicated content")


class MediaMetadataCreate(MediaMetadataBase):
    """Model used when writing a new media_metadata record."""
    article_id: str


class MediaMetadataInDB(MediaMetadataBase):
    """Model for a media_metadata record read from the database."""
    id: str
    article_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class MediaMetadataResponse(MediaMetadataBase):
    """API response for media_metadata."""
    id: str
    article_id: str
    created_at: datetime


# ── Official Metadata ──────────────────────────────────────────────────────────

class AnnouncementType(str, Enum):
    RESEARCH = "research"
    PRODUCT = "product"
    PARTNERSHIP = "partnership"
    POLICY = "policy"
    MILESTONE = "milestone"


class AudienceScope(str, Enum):
    GLOBAL = "global"
    INDUSTRY = "industry"
    NICHE = "niche"
    INTERNAL = "internal"


class OfficialMetadataBase(BaseModel):
    """Base fields shared by create and response models for official_metadata."""
    release_version: Optional[str] = Field(None, description='Release version, e.g. "v2.0" / "4.0"')
    product_name: Optional[str] = Field(None, description="Product name if not clear from title")
    product_url: Optional[str] = Field(None, description="Product page or download link")
    announcement_type: Optional[AnnouncementType] = Field(None, description="Type of official announcement")
    is_partnership: bool = Field(default=False, description="Announcement involves a partnership")
    partner_name: Optional[str] = Field(None, description="Partner organisation name")
    is_pricing_update: bool = Field(default=False, description="Pricing change announcement")
    pricing_change: Optional[str] = Field(None, description="Description of price change")
    tech_stack: list[str] = Field(default_factory=list, description='Technologies, e.g. ["PyTorch", "TPU", "RLHF"]')
    model_name: Optional[str] = Field(None, description="AI model name involved")
    benchmark_results: dict = Field(default_factory=dict, description='Benchmark scores, e.g. {"MMLU": "89%", "GSM8K": "95%"}')
    audience_scope: AudienceScope = Field(default=AudienceScope.INDUSTRY, description="Intended audience breadth")
    is_major_announcement: bool = Field(default=False, description="LLM judges this as a major announcement")


class OfficialMetadataCreate(OfficialMetadataBase):
    """Model used when writing a new official_metadata record."""
    article_id: str


class OfficialMetadataInDB(OfficialMetadataBase):
    """Model for an official_metadata record read from the database."""
    id: str
    article_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class OfficialMetadataResponse(OfficialMetadataBase):
    """API response for official_metadata."""
    id: str
    article_id: str
    created_at: datetime
