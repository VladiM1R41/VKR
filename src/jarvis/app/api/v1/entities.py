"""GET /entities/{id}, GET /entities/trending, POST/DELETE subscribe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db, get_default_user_id
from jarvis.db.models import (
    Entity,
    EntityProfile,
    News,
    NewsEntity,
    Source,
    UserEntitySubscription,
)

router = APIRouter(prefix="/entities", tags=["Entities"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RecentNewsOut(BaseModel):
    news_id: int
    title: str
    source_name: str
    published_at: Optional[datetime]


class EntityDetailOut(BaseModel):
    id: int
    name: str
    type: str
    normalized_name: str
    mention_count: int
    mention_freq_baseline: Optional[float]
    mention_freq_current: Optional[float]
    recent_news: list[RecentNewsOut]


class TrendingEntityOut(BaseModel):
    entity_id: int
    name: str
    type: str
    baseline_freq: Optional[float]
    current_freq: Optional[float]
    spike_ratio: Optional[float]


class TrendingEntitiesOut(BaseModel):
    items: list[TrendingEntityOut]
    period_hours: int


class SubscribeIn(BaseModel):
    alert_on_news: bool = True
    alert_on_spike: bool = True


class SubscribeOut(BaseModel):
    entity_id: int
    entity_name: str
    alert_on_news: bool
    alert_on_spike: bool
    subscribed: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/trending",
    response_model=TrendingEntitiesOut,
    summary="Трендовые сущности",
    description="Сущности с резким ростом упоминаний (spike detection) за указанный период.",
)
def get_trending(
    limit: int = Query(10, ge=1, le=50),
    period_hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db),
) -> TrendingEntitiesOut:
    rows = db.execute(
        select(
            EntityProfile.entity_id,
            Entity.name,
            Entity.type,
            EntityProfile.mention_freq_baseline,
            EntityProfile.mention_freq_current,
        )
        .join(Entity, Entity.id == EntityProfile.entity_id)
        .where(
            EntityProfile.mention_freq_current.is_not(None),
            EntityProfile.mention_freq_baseline.is_not(None),
            EntityProfile.mention_freq_current > EntityProfile.mention_freq_baseline * 1.5,
        )
        .order_by(
            (EntityProfile.mention_freq_current - EntityProfile.mention_freq_baseline).desc()
        )
        .limit(limit)
    ).all()

    items = []
    for r in rows:
        baseline = float(r[3]) if r[3] else None
        current = float(r[4]) if r[4] else None
        spike_ratio = round(current / baseline, 2) if baseline and baseline > 0 and current else None
        items.append(TrendingEntityOut(
            entity_id=int(r[0]),
            name=str(r[1]),
            type=str(r[2]),
            baseline_freq=baseline,
            current_freq=current,
            spike_ratio=spike_ratio,
        ))
    return TrendingEntitiesOut(items=items, period_hours=period_hours)


@router.get(
    "/{entity_id}",
    response_model=EntityDetailOut,
    summary="Профиль сущности",
    description="Детальная информация о сущности: частота упоминаний и последние новости.",
)
def get_entity(entity_id: int, db: Session = Depends(get_db)) -> EntityDetailOut:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Сущность не найдена")

    profile = db.scalar(
        select(EntityProfile).where(EntityProfile.entity_id == entity_id)
    )

    # Последние 5 новостей с этой сущностью
    recent_news_ids = db.scalars(
        select(NewsEntity.news_id)
        .where(NewsEntity.entity_id == entity_id)
        .order_by(NewsEntity.news_id.desc())
        .limit(5)
    ).all()

    recent_news = []
    for nid in recent_news_ids:
        news = db.get(News, nid)
        if news:
            source = db.get(Source, news.source_id)
            recent_news.append(RecentNewsOut(
                news_id=int(nid),
                title=str(news.title),
                source_name=source.name if source else "Unknown",
                published_at=news.published_at,
            ))

    return EntityDetailOut(
        id=int(entity.id),
        name=str(entity.name),
        type=str(entity.type),
        normalized_name=str(entity.normalized_name or entity.name),
        mention_count=int(entity.mention_count or 0),
        mention_freq_baseline=float(profile.mention_freq_baseline) if profile and profile.mention_freq_baseline else None,
        mention_freq_current=float(profile.mention_freq_current) if profile and profile.mention_freq_current else None,
        recent_news=recent_news,
    )


@router.post(
    "/{entity_id}/subscribe",
    response_model=SubscribeOut,
    summary="Подписаться на сущность",
    description="Создаёт подписку с настройками alert_on_news и alert_on_spike.",
)
def subscribe(
    entity_id: int,
    body: SubscribeIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> SubscribeOut:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Сущность не найдена")

    existing = db.get(UserEntitySubscription, {"user_id": user_id, "entity_id": entity_id})
    if existing is None:
        sub = UserEntitySubscription(
            user_id=user_id,
            entity_id=entity_id,
            alert_on_news=body.alert_on_news,
            alert_on_spike=body.alert_on_spike,
        )
        db.add(sub)
    else:
        existing.alert_on_news = body.alert_on_news
        existing.alert_on_spike = body.alert_on_spike

    db.commit()
    return SubscribeOut(
        entity_id=entity_id,
        entity_name=str(entity.name),
        alert_on_news=body.alert_on_news,
        alert_on_spike=body.alert_on_spike,
        subscribed=True,
    )


@router.delete(
    "/{entity_id}/subscribe",
    status_code=204,
    summary="Отписаться от сущности",
)
def unsubscribe(
    entity_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> Response:
    existing = db.get(UserEntitySubscription, {"user_id": user_id, "entity_id": entity_id})
    if existing is not None:
        db.delete(existing)
        db.commit()
    return Response(status_code=204)
