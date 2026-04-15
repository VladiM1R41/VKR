"""GET/PUT /profile, /preferences, /interactions — профиль пользователя."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db, get_default_user_id
from jarvis.db.models import (
    Entity,
    Source,
    Topic,
    User,
    UserEntitySubscription,
    UserInteraction,
    UserSourcePreference,
    UserTopicWeight,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["Profile"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TopicWeightOut(BaseModel):
    topic_id: int
    topic_name: str
    weight: float


class EntitySubscriptionOut(BaseModel):
    entity_id: int
    entity_name: str
    entity_type: str
    alert_on_news: bool
    alert_on_spike: bool


class SourcePreferenceOut(BaseModel):
    source_id: int
    source_name: str
    preference: str  # preferred | neutral | blocked


class UserSettingsOut(BaseModel):
    diversity_slider: float
    notify_channels: list[str]


class ProfileOut(BaseModel):
    user_id: int
    username: str
    email: Optional[str]
    topic_weights: list[TopicWeightOut]
    entity_subscriptions: list[EntitySubscriptionOut]
    source_preferences: list[SourcePreferenceOut]
    settings: UserSettingsOut


class PreferencesUpdateIn(BaseModel):
    diversity_slider: Optional[float] = Field(None, ge=0.0, le=1.0)
    notify_channels: Optional[list[str]] = None


class InteractionOut(BaseModel):
    news_id: int
    action: str
    created_at: datetime


class InteractionsOut(BaseModel):
    items: list[InteractionOut]
    total: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=ProfileOut,
    summary="Профиль пользователя",
    description="Возвращает полный профиль: веса тем, подписки на сущности, "
                "предпочтения источников и настройки персонализации.",
)
def get_profile(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> ProfileOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Topic weights
    topic_rows = db.execute(
        select(UserTopicWeight.topic_id, UserTopicWeight.weight, Topic.name)
        .join(Topic, Topic.id == UserTopicWeight.topic_id)
        .where(UserTopicWeight.user_id == user_id)
        .order_by(UserTopicWeight.weight.desc())
    ).all()
    topic_weights = [
        TopicWeightOut(topic_id=int(r[0]), topic_name=str(r[2]), weight=float(r[1]))
        for r in topic_rows
    ]

    # Entity subscriptions
    sub_rows = db.execute(
        select(
            UserEntitySubscription.entity_id,
            Entity.name,
            Entity.type,
            UserEntitySubscription.alert_on_news,
            UserEntitySubscription.alert_on_spike,
        )
        .join(Entity, Entity.id == UserEntitySubscription.entity_id)
        .where(UserEntitySubscription.user_id == user_id)
    ).all()
    entity_subscriptions = [
        EntitySubscriptionOut(
            entity_id=int(r[0]),
            entity_name=str(r[1]),
            entity_type=str(r[2]),
            alert_on_news=bool(r[3]),
            alert_on_spike=bool(r[4]),
        )
        for r in sub_rows
    ]

    # Source preferences
    pref_rows = db.execute(
        select(UserSourcePreference.source_id, Source.name, UserSourcePreference.preference)
        .join(Source, Source.id == UserSourcePreference.source_id)
        .where(UserSourcePreference.user_id == user_id)
    ).all()
    source_preferences = [
        SourcePreferenceOut(source_id=int(r[0]), source_name=str(r[1]), preference=str(r[2]))
        for r in pref_rows
    ]

    settings_data = dict(user.settings or {})
    settings = UserSettingsOut(
        diversity_slider=float(settings_data.get("diversity_slider", 0.3)),
        notify_channels=list(settings_data.get("notify_channels", ["web"])),
    )

    return ProfileOut(
        user_id=int(user.id),
        username=str(user.username),
        email=user.email,
        topic_weights=topic_weights,
        entity_subscriptions=entity_subscriptions,
        source_preferences=source_preferences,
        settings=settings,
    )


@router.put(
    "/preferences",
    response_model=UserSettingsOut,
    summary="Обновить настройки персонализации",
)
def update_preferences(
    body: PreferencesUpdateIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> UserSettingsOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    settings = dict(user.settings or {})
    if body.diversity_slider is not None:
        settings["diversity_slider"] = body.diversity_slider
    if body.notify_channels is not None:
        settings["notify_channels"] = body.notify_channels
    user.settings = settings
    db.commit()

    return UserSettingsOut(
        diversity_slider=float(settings.get("diversity_slider", 0.3)),
        notify_channels=list(settings.get("notify_channels", ["web"])),
    )


@router.get(
    "/interactions",
    response_model=InteractionsOut,
    summary="История взаимодействий",
    description="Клики, лайки, сохранения и скрытия новостей пользователем.",
)
def get_interactions(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> InteractionsOut:
    total = db.scalar(
        select(func.count()).select_from(UserInteraction).where(UserInteraction.user_id == user_id)
    ) or 0
    rows = db.scalars(
        select(UserInteraction)
        .where(UserInteraction.user_id == user_id)
        .order_by(UserInteraction.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        InteractionOut(
            news_id=int(r.news_id),
            action=str(r.action),
            created_at=r.created_at,
        )
        for r in rows
    ]
    return InteractionsOut(items=items, total=int(total))
