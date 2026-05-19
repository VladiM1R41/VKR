"""Shared API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


class PageMeta(BaseModel):
    limit: int
    offset: int = 0
    total: int


class SourceBrief(BaseModel):
    id: int
    name: str
    type: str
    url: str | None = None
    health_status: str | None = None
    trust_score: float | None = None


class TopicView(BaseModel):
    id: int
    name: str
    confidence: float | None = None


class EntityView(BaseModel):
    id: int
    name: str
    type: str
    normalized_name: str | None = None
    mention_count: int | None = None


class TimestampedCount(BaseModel):
    label: str
    count: int
    updated_at: datetime | None = None


class GenericMessage(BaseModel):
    ok: bool = True
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

