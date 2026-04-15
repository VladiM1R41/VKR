"""Pydantic contracts for implicit personalization signals."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class InteractionEventRequest(BaseModel):
    """One user interaction event with an article."""

    user_id: int = Field(..., ge=1)
    news_id: int = Field(..., ge=1)
    action: str
    dwell_time_sec: float | None = Field(default=None, ge=0.0)
    search_log_id: int | None = Field(default=None, ge=1)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("action")
    @classmethod
    def _normalize_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {
            "click",
            "read",
            "read_long",
            "click_short",
            "like",
            "dislike",
            "save",
            "share",
            "hide",
            "skip",
        }
        if normalized not in allowed:
            raise ValueError(f"Unsupported action: {value}")
        return normalized

    @model_validator(mode="after")
    def _validate_dwell_usage(self) -> "InteractionEventRequest":
        if self.action in {"read", "read_long", "click_short"} and self.dwell_time_sec is None:
            return self
        return self


class InteractionEventResponse(BaseModel):
    """Persisted interaction plus derived normalized signal."""

    interaction_id: int
    user_id: int
    news_id: int
    stored_action: str
    derived_signal: float
    dwell_time_sec: float | None = None
    search_log_id: int | None = None
    created_at: datetime | None = None


class SeenHistoryRecord(BaseModel):
    """One seen-article marker in short-term session history."""

    news_id: int
    seen_at: datetime | None = None


class SeenHistoryResponse(BaseModel):
    """Short-term seen state for a user/session."""

    user_id: int | None = None
    session_id: str | None = None
    news_ids: list[int] = Field(default_factory=list)
