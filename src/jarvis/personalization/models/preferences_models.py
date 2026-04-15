"""Pydantic contracts for explicit personalization preferences."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class UserProfilePatch(BaseModel):
    """Explicit user-facing profile fields."""

    user_id: int | None = Field(default=None, ge=1)
    username: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    telegram_id: int | None = Field(default=None)
    settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _require_identity(self) -> "UserProfilePatch":
        if self.user_id is None and not self.username:
            raise ValueError("Either user_id or username must be provided")
        return self


class TopicPreferenceInput(BaseModel):
    """User-configurable topic weight."""

    topic_id: int = Field(..., ge=1)
    weight: float = Field(..., ge=0.0, le=1.0)


class EntityPreferenceInput(BaseModel):
    """User-configurable entity weight."""

    entity_id: int = Field(..., ge=1)
    weight: float = Field(..., ge=0.0, le=1.0)


class EntitySubscriptionInput(BaseModel):
    """Explicit entity subscription settings."""

    entity_id: int = Field(..., ge=1)
    alert_on_spike: bool = True
    alert_on_news: bool = True


class TrackedKeywordInput(BaseModel):
    """Arbitrary keyword tracked by the user."""

    keyword: str = Field(..., min_length=1, max_length=200)

    @field_validator("keyword")
    @classmethod
    def _normalize_keyword(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("keyword must not be empty")
        return normalized


class SourcePreferenceInput(BaseModel):
    """User relation to a source."""

    source_id: int = Field(..., ge=1)
    preference: str

    @field_validator("preference")
    @classmethod
    def _validate_preference(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"preferred", "neutral", "blocked"}:
            raise ValueError("preference must be one of preferred, neutral, blocked")
        return normalized


class ExplicitPreferencesUpdateRequest(BaseModel):
    """Full explicit-preferences update payload for one user."""

    profile: UserProfilePatch
    topic_weights: list[TopicPreferenceInput] = Field(default_factory=list)
    entity_weights: list[EntityPreferenceInput] = Field(default_factory=list)
    entity_subscriptions: list[EntitySubscriptionInput] = Field(default_factory=list)
    tracked_keywords: list[TrackedKeywordInput] = Field(default_factory=list)
    source_preferences: list[SourcePreferenceInput] = Field(default_factory=list)


class UserProfileView(BaseModel):
    """Profile view returned by the service."""

    user_id: int
    username: str
    email: str | None = None
    telegram_id: int | None = None
    settings: dict[str, Any]
    created_at: datetime | None = None
    last_active_at: datetime | None = None


class TopicPreferenceView(BaseModel):
    """Topic weight plus topic name."""

    topic_id: int
    name: str | None = None
    weight: float


class EntityPreferenceView(BaseModel):
    """Entity weight plus entity name."""

    entity_id: int
    name: str | None = None
    weight: float


class EntitySubscriptionView(BaseModel):
    """Entity subscription plus entity name."""

    entity_id: int
    name: str | None = None
    alert_on_spike: bool
    alert_on_news: bool


class TrackedKeywordView(BaseModel):
    """Tracked keyword value."""

    keyword: str


class SourcePreferenceView(BaseModel):
    """Source preference plus source name."""

    source_id: int
    name: str | None = None
    preference: str


class ExplicitPreferencesResponse(BaseModel):
    """Complete explicit-preferences snapshot for one user."""

    profile: UserProfileView
    topic_weights: list[TopicPreferenceView] = Field(default_factory=list)
    entity_weights: list[EntityPreferenceView] = Field(default_factory=list)
    entity_subscriptions: list[EntitySubscriptionView] = Field(default_factory=list)
    tracked_keywords: list[TrackedKeywordView] = Field(default_factory=list)
    source_preferences: list[SourcePreferenceView] = Field(default_factory=list)
