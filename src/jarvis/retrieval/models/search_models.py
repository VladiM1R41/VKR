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
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
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
