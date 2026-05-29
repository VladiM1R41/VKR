"""Digest API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DigestGenerateRequest(BaseModel):
    digest_type: str = Field("on_demand", pattern="^(morning|evening|weekly|on_demand)$")
    query: str = Field("главные новости сегодня", min_length=1, max_length=500)
    limit: int = Field(40, ge=10, le=50)
    digest_style: str | None = Field(None, pattern="^(brief|detailed|analytical|editorial)$")
    topics: list[str] = Field(default_factory=list)
    period_hours: int | None = Field(None, ge=1, le=24 * 30)
    force: bool = False


class DigestItemView(BaseModel):
    news_id: int
    position: int
    snippet: str | None = None
    title: str | None = None
    url: str | None = None


class DigestResponse(BaseModel):
    id: int
    digest_type: str
    content_text: str
    news_count: int
    topics_covered: list[str] = Field(default_factory=list)
    generation_log_id: int | None = None
    generated_at: datetime
    audio_path: str | None = None
    items: list[DigestItemView] = Field(default_factory=list)


class DigestListResponse(BaseModel):
    items: list[DigestResponse]
    total: int
    limit: int
    offset: int


class DigestAudioStatusResponse(BaseModel):
    status: str
    detail: dict = Field(default_factory=dict)
