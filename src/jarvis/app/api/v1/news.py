"""GET /news/{id}, GET /news/{id}/related — детали и связанные новости."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db
from jarvis.db.models import (
    Chunk,
    Entity,
    News,
    NewsEntity,
    NewsTopic,
    Source,
    Topic,
)

router = APIRouter(prefix="/news", tags=["News"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class NewsDetailOut(BaseModel):
    id: int
    title: str
    content: Optional[str]
    snippet_lead: Optional[str]
    url: Optional[str]
    source_id: int
    source_name: str
    published_at: Optional[datetime]
    language: str
    information_type: Optional[str]
    urgency: Optional[str]
    content_grade: Optional[int]
    entities: list[str]
    topics: list[str]
    chunk_count: int
    event_cluster_id: Optional[int]


class RelatedNewsOut(BaseModel):
    id: int
    title: str
    source_name: str
    published_at: Optional[datetime]
    snippet_lead: Optional[str]


class RelatedNewsListOut(BaseModel):
    items: list[RelatedNewsOut]
    cluster_id: Optional[int]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/{news_id}",
    response_model=NewsDetailOut,
    summary="Детали новости",
    description="Возвращает полную информацию о новости: текст, сущности, темы, чанки.",
)
def get_news(news_id: int, db: Session = Depends(get_db)) -> NewsDetailOut:
    news = db.get(News, news_id)
    if news is None:
        raise HTTPException(status_code=404, detail="Новость не найдена")

    source = db.get(Source, news.source_id)
    source_name = source.name if source else "Unknown"

    entity_ids = db.scalars(
        select(NewsEntity.entity_id).where(NewsEntity.news_id == news_id)
    ).all()
    entity_names = []
    if entity_ids:
        entity_names = list(
            db.scalars(select(Entity.name).where(Entity.id.in_(entity_ids))).all()
        )

    topic_ids = db.scalars(
        select(NewsTopic.topic_id).where(NewsTopic.news_id == news_id)
    ).all()
    topic_names = []
    if topic_ids:
        topic_names = list(
            db.scalars(select(Topic.name).where(Topic.id.in_(topic_ids))).all()
        )

    chunk_count = db.scalar(
        select(__import__("sqlalchemy", fromlist=["func"]).func.count())
        .select_from(Chunk)
        .where(Chunk.news_id == news_id)
    ) or 0

    return NewsDetailOut(
        id=int(news.id),
        title=str(news.title),
        content=news.content,
        snippet_lead=news.snippet_lead,
        url=news.canonical_url,
        source_id=int(news.source_id),
        source_name=source_name,
        published_at=news.published_at,
        language=str(news.language or "ru"),
        information_type=news.information_type,
        urgency=news.urgency,
        content_grade=news.content_grade,
        entities=list(entity_names),
        topics=list(topic_names),
        chunk_count=int(chunk_count),
        event_cluster_id=news.event_cluster_id,
    )


@router.get(
    "/{news_id}/related",
    response_model=RelatedNewsListOut,
    summary="Связанные новости",
    description="Новости из того же событийного кластера (event_cluster_id) из разных источников.",
)
def get_related(
    news_id: int,
    limit: int = 5,
    db: Session = Depends(get_db),
) -> RelatedNewsListOut:
    news = db.get(News, news_id)
    if news is None:
        raise HTTPException(status_code=404, detail="Новость не найдена")

    cluster_id = news.event_cluster_id
    if cluster_id is None:
        return RelatedNewsListOut(items=[], cluster_id=None)

    rows = db.scalars(
        select(News)
        .where(News.event_cluster_id == cluster_id, News.id != news_id)
        .order_by(News.published_at.desc())
        .limit(limit)
    ).all()

    items = []
    for r in rows:
        source = db.get(Source, r.source_id)
        items.append(RelatedNewsOut(
            id=int(r.id),
            title=str(r.title),
            source_name=source.name if source else "Unknown",
            published_at=r.published_at,
            snippet_lead=r.snippet_lead,
        ))

    return RelatedNewsListOut(items=items, cluster_id=int(cluster_id))
