"""News API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from jarvis.app.schemas.common import EntityView, PageMeta, SourceBrief, TopicView


class NewsSummary(BaseModel):
    id: int
    title: str
    snippet: str | None = None
    source: SourceBrief
    url: str
    published_at: datetime | None = None
    ingested_at: datetime
    content_grade: int
    information_type: str
    urgency: str
    is_uncertain: bool
    processed: bool
    topics: list[TopicView] = Field(default_factory=list)
    entities: list[EntityView] = Field(default_factory=list)


class NewsFeedResponse(BaseModel):
    items: list[NewsSummary]
    meta: PageMeta


class NewsSourceFilterItem(SourceBrief):
    news_count: int = 0
    processed_count: int = 0


class NewsSourceFiltersResponse(BaseModel):
    items: list[NewsSourceFilterItem]


class NewsTopicFilterItem(BaseModel):
    id: int
    name: str
    news_count: int = 0


class NewsTopicFiltersResponse(BaseModel):
    items: list[NewsTopicFilterItem]


class NewsDetail(NewsSummary):
    content: str | None = None
    canonical_url: str
    language: str
    content_status: str
    extraction_method: str | None = None
    event_cluster_id: int | None = None
    chunk_count: int = 0
    extra: dict = Field(default_factory=dict)


class RelatedNewsResponse(BaseModel):
    items: list[NewsSummary]
