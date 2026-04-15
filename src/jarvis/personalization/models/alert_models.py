"""Models for Layer 4 alert candidates."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AlertCandidate(BaseModel):
    """One candidate alert produced by Layer 4."""

    user_id: int
    news_id: int
    alert_type: str
    title: str
    body: str
    entity_id: int | None = None
    topic: str | None = None
    source_name: str | None = None
    urgency: str | None = None
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    published_at: datetime | None = None


class AlertBatch(BaseModel):
    """Collection of alert candidates for one user/check run."""

    user_id: int
    alerts: list[AlertCandidate] = Field(default_factory=list)
