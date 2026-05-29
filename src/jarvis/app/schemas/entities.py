"""Entity API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from jarvis.app.schemas.news import NewsSummary


class EntityProfileView(BaseModel):
    mention_freq_baseline: float | None = None
    mention_freq_current: float | None = None
    source_diversity: float = 0.0
    trend_direction: str = "stable"
    last_updated: datetime | None = None


class TrendingEntityItem(BaseModel):
    entity_id: int
    name: str
    type: str
    normalized_name: str | None = None
    mention_freq_baseline: float | None = None
    mention_freq_current: float | None = None
    source_diversity: float = 0.0
    trend_direction: str = "stable"
    last_updated: datetime | None = None


class TrendingEntitiesResponse(BaseModel):
    items: list[TrendingEntityItem] = Field(default_factory=list)


class EntityDetailResponse(BaseModel):
    id: int
    name: str
    type: str
    normalized_name: str | None = None
    mention_count: int
    profile: EntityProfileView
    recent_news: list[NewsSummary] = Field(default_factory=list)
