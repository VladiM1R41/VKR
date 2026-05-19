"""Pydantic models for personalized ranking output."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PersonalizedResult(BaseModel):
    """One personalized result with explainability."""

    news_id: int
    source_id: int
    source_name: str
    title: str
    snippet: str
    base_score: float
    personalized_score: float
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    explanation: str | None = None
    personalization_reasons: list[str] = Field(default_factory=list)
    # Поля из Layer 3, пробрасываемые насквозь (нужны Layer 5 и Layer 6)
    chunk_id: str | None = None
    rerank_score: float | None = None
    trust_score: float = 0.5
    content_grade: int = 6
    information_type: str = "daily"
    urgency: str = "normal"
    event_cluster_id: int | None = None
    value_score: float | None = None
    freshness: float | None = None
    completeness: float | None = None
    cluster_support: float | None = None
    is_uncertain: bool = False


class PersonalizedSearchResponse(BaseModel):
    """Personalized ranking response for Layer 4."""

    query: str
    corrected_query: str | None = None
    intent: str
    total: int
    results: list[PersonalizedResult]
