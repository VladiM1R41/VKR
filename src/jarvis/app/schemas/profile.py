"""Profile and feedback API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    news_id: int = Field(..., ge=1)
    action: str = Field(..., pattern="^(click|read|like|dislike|save|hide|share|read_long|click_short|skip)$")
    dwell_time_sec: float | None = Field(None, ge=0)
    search_log_id: int | None = Field(None, ge=1)
    session_id: str | None = None


class FeedbackResponse(BaseModel):
    recorded: bool
    interaction_id: int
    stored_action: str
    derived_signal: float


class InteractionItem(BaseModel):
    id: int
    news_id: int
    title: str | None = None
    action: str
    dwell_time_sec: float | None = None
    search_log_id: int | None = None
    created_at: datetime


class InteractionsResponse(BaseModel):
    items: list[InteractionItem]
    total: int
    limit: int
    offset: int


class EntitySubscribeRequest(BaseModel):
    alert_on_spike: bool = True
    alert_on_news: bool = True

class EntitySubscribeResponse(BaseModel):
    entity_id: int
    alert_on_spike: bool
    alert_on_news: bool

