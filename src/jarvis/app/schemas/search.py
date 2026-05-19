"""Search API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from jarvis.retrieval.models.search_models import SearchFilters


class SearchApiRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(10, ge=1, le=50)
    filters: SearchFilters | None = None


class SearchApiResult(BaseModel):
    news_id: int
    source_id: int
    source_name: str
    title: str
    snippet: str
    base_score: float
    personalized_score: float
    retrieval_mode: str | None = None
    rerank_score: float | None = None
    trust_score: float
    content_grade: int
    information_type: str
    urgency: str
    event_cluster_id: int | None = None
    published_at: datetime | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    explanation: str | None = None
    personalization_reasons: list[str] = Field(default_factory=list)


class SearchApiResponse(BaseModel):
    query: str
    corrected_query: str | None = None
    intent: str
    total: int
    search_time_ms: float
    results: list[SearchApiResult]


class SearchSuggestionResponse(BaseModel):
    suggestions: list[str]


class SearchLogItem(BaseModel):
    id: int
    query_text: str
    resolved_query: str | None = None
    intent: str | None = None
    num_results: int
    retrieval_time_ms: int
    cache_hit: bool
    retrieval_mode: str
    top_result_ids: list[int]
    created_at: datetime


class SearchLogsResponse(BaseModel):
    items: list[SearchLogItem]
    total: int
    limit: int
    offset: int

