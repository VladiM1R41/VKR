"""Pydantic models for search request and response."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Optional filters for search."""

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    source_ids: Optional[list[int]] = None
    topics: Optional[list[str]] = None
    zone: Optional[str] = Field(None, pattern="^(title|body)$")
    content_grade: Optional[int] = Field(None, ge=1, le=6)
    content_grade_max: Optional[int] = Field(None, ge=1, le=6)
    urgency: Optional[str] = Field(None, pattern="^(critical|high|normal)$")
    information_type: Optional[str] = Field(None, pattern="^(breaking|daily|analytics|reference)$")
    event_cluster_id: Optional[int] = None
    language: str = "ru"


class SearchRequest(BaseModel):
    """User search request."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    limit: int = Field(10, ge=1, le=50, description="Max results to return")
    filters: Optional[SearchFilters] = None


class SearchResult(BaseModel):
    """One search result with metadata and explainability."""

    chunk_id: str
    news_id: int
    source_id: int
    source_name: str
    title: str
    snippet: str
    score: float
    rerank_score: Optional[float] = None
    retrieval_score: Optional[float] = None
    retrieval_mode: str = "qdrant_hybrid"
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    trust_score: float = 0.5
    content_grade: int = 6
    information_type: str = "daily"
    urgency: str = "normal"
    event_cluster_id: Optional[int] = None
    value_score: Optional[float] = None
    freshness: Optional[float] = None
    completeness: Optional[float] = None
    cluster_support: Optional[float] = None
    is_uncertain: bool = False
    explanation: Optional[str] = None


class SearchResponse(BaseModel):
    """Complete search response."""

    query: str
    corrected_query: Optional[str] = None
    intent: str  # FACTUAL | CAPABILITY | INTENT
    results: list[SearchResult]
    total: int
    search_time_ms: float


class SearchResultAggregated(BaseModel):
    """Aggregated result: one article (best chunk)."""

    news_id: int
    source_id: int
    source_name: str
    title: str
    snippet: str
    score: float
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    chunk_count: int = 1
    explanation: Optional[str] = None
