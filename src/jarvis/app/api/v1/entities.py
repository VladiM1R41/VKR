"""Entity endpoints over Layer 2 profiles and Layer 4 subscriptions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.news import NewsSummary
from jarvis.app.schemas.profile import EntitySubscribeRequest, EntitySubscribeResponse
from jarvis.db.models import Entity, EntityProfile, News, NewsEntity, Source, UserEntitySubscription
from jarvis.app.api.v1.news import _load_entities, _load_topics, _summary

router = APIRouter()


@router.get("/trending")
def trending_entities(
    session: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=100),
    period_hours: int = Query(24, ge=1, le=168),
) -> dict:
    since = datetime.now(UTC) - timedelta(hours=period_hours)
    rows = session.execute(
        select(Entity, EntityProfile)
        .join(EntityProfile, EntityProfile.entity_id == Entity.id)
        .where(
            EntityProfile.last_updated >= since,
            EntityProfile.mention_freq_current.is_not(None),
            EntityProfile.mention_freq_baseline.is_not(None),
            EntityProfile.mention_freq_current > EntityProfile.mention_freq_baseline * 1.5,
        )
        .order_by(desc(EntityProfile.mention_freq_current - EntityProfile.mention_freq_baseline))
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                "entity_id": entity.id,
                "name": entity.name,
                "type": entity.type,
                "normalized_name": entity.normalized_name,
                "mention_freq_baseline": profile.mention_freq_baseline,
                "mention_freq_current": profile.mention_freq_current,
                "source_diversity": profile.source_diversity,
                "trend_direction": profile.trend_direction,
                "last_updated": profile.last_updated,
            }
            for entity, profile in rows
        ]
    }


@router.get("/{entity_id}")
def entity_detail(
    entity_id: int,
    session: Session = Depends(get_db),
    limit: int = Query(5, ge=1, le=20),
) -> dict:
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    profile = session.get(EntityProfile, entity_id)
    rows = session.execute(
        select(News, Source)
        .join(NewsEntity, NewsEntity.news_id == News.id)
        .join(Source, Source.id == News.source_id)
        .where(NewsEntity.entity_id == entity_id)
        .order_by(desc(News.published_at).nullslast(), desc(News.ingested_at))
        .limit(limit)
    ).all()
    ids = [news.id for news, _ in rows]
    topics = _load_topics(session, ids)
    entities = _load_entities(session, ids)
    recent_news: list[NewsSummary] = [
        _summary(news, source, topics.get(news.id, []), entities.get(news.id, []))
        for news, source in rows
    ]
    return {
        "id": entity.id,
        "name": entity.name,
        "type": entity.type,
        "normalized_name": entity.normalized_name,
        "mention_count": entity.mention_count,
        "profile": {
            "mention_freq_baseline": profile.mention_freq_baseline if profile else None,
            "mention_freq_current": profile.mention_freq_current if profile else None,
            "source_diversity": profile.source_diversity if profile else 0,
            "trend_direction": profile.trend_direction if profile else "stable",
            "last_updated": profile.last_updated if profile else None,
        },
        "recent_news": [item.model_dump(mode="json") for item in recent_news],
    }


@router.post("/{entity_id}/subscribe", response_model=EntitySubscribeResponse)
def subscribe_entity(
    entity_id: int,
    request: EntitySubscribeRequest,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> EntitySubscribeResponse:
    if session.get(Entity, entity_id) is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    subscription = session.get(UserEntitySubscription, {"user_id": user_id, "entity_id": entity_id})
    if subscription is None:
        subscription = UserEntitySubscription(user_id=user_id, entity_id=entity_id)
        session.add(subscription)
    subscription.alert_on_spike = request.alert_on_spike
    subscription.alert_on_news = request.alert_on_news
    session.commit()
    return EntitySubscribeResponse(
        entity_id=entity_id,
        alert_on_spike=subscription.alert_on_spike,
        alert_on_news=subscription.alert_on_news,
    )


@router.delete("/{entity_id}/subscribe")
def unsubscribe_entity(
    entity_id: int,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, str]:
    session.execute(
        delete(UserEntitySubscription).where(
            UserEntitySubscription.user_id == user_id,
            UserEntitySubscription.entity_id == entity_id,
        )
    )
    session.commit()
    return {"status": "deleted"}
