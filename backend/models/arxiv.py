"""
Pydantic models for arxiv_metadata table.

Covers: arXiv cs.AI / cs.LG / cs.CL / cs.CV
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ArxivAuthor(BaseModel):
    name: str
    affiliation: Optional[str] = None


class ArxivMetadataBase(BaseModel):
    """Base fields shared by create and response models."""
    arxiv_id: str = Field(..., description='arXiv ID without version, e.g. "2404.12345"')
    arxiv_id_versioned: Optional[str] = Field(None, description='arXiv ID with version, e.g. "2404.12345v1"')
    categories: list[str] = Field(default_factory=list, description='All arXiv categories')
    primary_category: str = Field(..., description='Primary arXiv category, e.g. "cs.CL"')
    sub_categories: Optional[list[str]] = Field(None, description='Secondary categories')
    authors: list[ArxivAuthor] = Field(default_factory=list, description='Parsed author list')
    first_author: Optional[str] = Field(None, description='First author name for quick query')
    author_count: int = Field(default=0, description='Total number of authors')
    doi: Optional[str] = Field(None, description='DOI if published in a journal')
    journal_ref: Optional[str] = Field(None, description='Journal reference string')
    comments: Optional[str] = Field(None, description='Author comments (may contain important notes)')
    citation_count: int = Field(default=0, description='Citation count from arXiv API')
    reference_count: int = Field(default=0, description='Number of references')
    author_hindex_avg: float = Field(default=0.0, description='Average author h-index')
    claims: list[str] = Field(default_factory=list, description='Key technical claims extracted from abstract')
    limitations: list[str] = Field(default_factory=list, description='Self-reported limitations')
    is_novelty: bool = Field(default=False, description='Title/abstract declares novelty ("first", "novel", "new approach")')
    is_sota: bool = Field(default=False, description='Title/abstract claims state-of-the-art results')
    content_label: Optional[str] = Field(
        None,
        description="LLM content type: 'breakthrough' / 'improvement' / 'benchmark' / 'survey' / 'application'"
    )
    impact_score: float = Field(default=0.5, ge=0.0, le=1.0, description='LLM-assessed impact score')


class ArxivMetadataCreate(ArxivMetadataBase):
    """Model used when writing a new arxiv_metadata record."""
    article_id: str


class ArxivMetadataInDB(ArxivMetadataBase):
    """Model for an arxiv_metadata record read from the database."""
    id: str
    article_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class ArxivMetadataResponse(ArxivMetadataBase):
    """API response for arxiv_metadata."""
    id: str
    article_id: str
    created_at: datetime
