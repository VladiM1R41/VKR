"""News feed and article endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, case, desc, func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.common import EntityView, PageMeta, SourceBrief, TopicView
from jarvis.app.schemas.news import (
    NewsDetail,
    NewsFeedResponse,
    NewsSourceFilterItem,
    NewsSourceFiltersResponse,
    NewsSummary,
    NewsTopicFilterItem,
    NewsTopicFiltersResponse,
    RelatedNewsResponse,
)
from jarvis.db.models import Chunk, Entity, News, NewsEntity, NewsTopic, Source, Topic, UserSourcePreference

router = APIRouter()


def _source_view(source: Source) -> SourceBrief:
    return SourceBrief(
        id=source.id,
        name=source.name,
        type=source.type,
        url=source.url,
        health_status=source.health_status,
        trust_score=source.trust_score,
    )


def _load_topics(session: Session, news_ids: list[int]) -> dict[int, list[TopicView]]:
    if not news_ids:
        return {}
    stmt = (
        select(NewsTopic.news_id, Topic.id, Topic.name, NewsTopic.confidence)
        .join(Topic, Topic.id == NewsTopic.topic_id)
        .where(NewsTopic.news_id.in_(news_ids))
    )
    result: dict[int, list[TopicView]] = {news_id: [] for news_id in news_ids}
    for news_id, topic_id, name, confidence in session.execute(stmt):
        result.setdefault(news_id, []).append(TopicView(id=topic_id, name=name, confidence=confidence))
    return result


def _load_entities(session: Session, news_ids: list[int]) -> dict[int, list[EntityView]]:
    if not news_ids:
        return {}
    stmt = (
        select(NewsEntity.news_id, Entity.id, Entity.name, Entity.type, Entity.normalized_name, NewsEntity.mention_count)
        .join(Entity, Entity.id == NewsEntity.entity_id)
        .where(NewsEntity.news_id.in_(news_ids))
    )
    result: dict[int, list[EntityView]] = {news_id: [] for news_id in news_ids}
    for news_id, entity_id, name, entity_type, normalized_name, mention_count in session.execute(stmt):
        result.setdefault(news_id, []).append(
            EntityView(
                id=entity_id,
                name=name,
                type=entity_type,
                normalized_name=normalized_name,
                mention_count=mention_count,
            )
        )
    return result


def _summary(news: News, source: Source, topics: list[TopicView], entities: list[EntityView]) -> NewsSummary:
    return NewsSummary(
        id=news.id,
        title=news.title,
        snippet=news.snippet_lead or (news.content[:280] if news.content else None),
        source=_source_view(source),
        url=news.url,
        published_at=news.published_at,
        ingested_at=news.ingested_at,
        content_grade=news.content_grade,
        information_type=news.information_type,
        urgency=news.urgency,
        is_uncertain=news.is_uncertain,
        processed=news.processed,
        topics=topics,
        entities=entities,
    )


def _apply_feed_filters(
    stmt: Select[tuple[News, Source]],
    *,
    source_id: int | None,
    source_ids: list[int] | None,
    topic: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    content_grade_max: int | None,
    processed_only: bool,
) -> Select[tuple[News, Source]]:
    if source_id is not None:
        stmt = stmt.where(News.source_id == source_id)
    elif source_ids:
        stmt = stmt.where(News.source_id.in_(sorted(set(source_ids))))
    if date_from is not None:
        stmt = stmt.where(News.published_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(News.published_at <= date_to)
    if content_grade_max is not None:
        stmt = stmt.where(News.content_grade <= content_grade_max)
    if processed_only:
        stmt = stmt.where(News.processed.is_(True))
    if topic:
        stmt = stmt.join(NewsTopic, NewsTopic.news_id == News.id).join(Topic, Topic.id == NewsTopic.topic_id)
        stmt = stmt.where(Topic.name == topic)
    return stmt


def _load_source_preferences(session: Session, user_id: int) -> tuple[set[int], set[int]]:
    rows = session.scalars(
        select(UserSourcePreference).where(UserSourcePreference.user_id == user_id)
    ).all()
    preferred = {int(row.source_id) for row in rows if row.preference == "preferred"}
    blocked = {int(row.source_id) for row in rows if row.preference == "blocked"}
    return preferred, blocked


@router.get("/feed", response_model=NewsFeedResponse)
def get_news_feed(
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source_id: int | None = None,
    source_ids: list[int] | None = Query(None),
    topic: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    content_grade_max: int | None = Query(None, ge=1, le=6),
    processed_only: bool = False,
    personalized: bool = True,
) -> NewsFeedResponse:
    base = select(News, Source).join(Source, Source.id == News.source_id)
    filtered = _apply_feed_filters(
        base,
        source_id=source_id,
        source_ids=source_ids,
        topic=topic,
        date_from=date_from,
        date_to=date_to,
        content_grade_max=content_grade_max,
        processed_only=processed_only,
    )
    preferred_source_ids: set[int] = set()
    if personalized:
        preferred_source_ids, blocked_source_ids = _load_source_preferences(session, user_id)
        if blocked_source_ids and source_id is None and not source_ids:
            filtered = filtered.where(News.source_id.not_in(blocked_source_ids))

    total = session.scalar(select(func.count()).select_from(filtered.subquery())) or 0
    source_priority = case((News.source_id.in_(preferred_source_ids), 1), else_=0)
    rows = session.execute(
        filtered.order_by(
            desc(News.published_at).nullslast(),
            desc(News.ingested_at),
            desc(source_priority),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    news_ids = [row[0].id for row in rows]
    topics = _load_topics(session, news_ids)
    entities = _load_entities(session, news_ids)
    items = [_summary(news, source, topics.get(news.id, []), entities.get(news.id, [])) for news, source in rows]
    return NewsFeedResponse(items=items, meta=PageMeta(limit=limit, offset=offset, total=total))


@router.get("/sources", response_model=NewsSourceFiltersResponse)
def get_news_sources(session: Session = Depends(get_db)) -> NewsSourceFiltersResponse:
    total_counts = dict(
        session.execute(select(News.source_id, func.count()).group_by(News.source_id)).all()
    )
    processed_counts = dict(
        session.execute(
            select(News.source_id, func.count()).where(News.processed.is_(True)).group_by(News.source_id)
        ).all()
    )
    sources = session.scalars(select(Source).order_by(Source.name)).all()
    return NewsSourceFiltersResponse(
        items=[
            NewsSourceFilterItem(
                **_source_view(source).model_dump(),
                news_count=int(total_counts.get(source.id, 0)),
                processed_count=int(processed_counts.get(source.id, 0)),
            )
            for source in sources
        ]
    )


@router.get("/topics", response_model=NewsTopicFiltersResponse)
def get_news_topics(session: Session = Depends(get_db)) -> NewsTopicFiltersResponse:
    rows = session.execute(
        select(Topic.id, Topic.name, func.count(NewsTopic.news_id))
        .join(NewsTopic, NewsTopic.topic_id == Topic.id)
        .group_by(Topic.id, Topic.name)
        .order_by(func.count(NewsTopic.news_id).desc(), Topic.name)
    ).all()
    return NewsTopicFiltersResponse(
        items=[NewsTopicFilterItem(id=topic_id, name=name, news_count=int(count)) for topic_id, name, count in rows]
    )


@router.get("/{news_id}", response_model=NewsDetail)
def get_news(news_id: int, session: Session = Depends(get_db)) -> NewsDetail:
    row = session.execute(
        select(News, Source).join(Source, Source.id == News.source_id).where(News.id == news_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="News item not found")
    news, source = row
    topics = _load_topics(session, [news.id]).get(news.id, [])
    entities = _load_entities(session, [news.id]).get(news.id, [])
    chunk_count = session.scalar(select(func.count()).select_from(Chunk).where(Chunk.news_id == news.id)) or 0
    base = _summary(news, source, topics, entities).model_dump()
    return NewsDetail(
        **base,
        content=news.content,
        canonical_url=news.canonical_url,
        language=news.language,
        content_status=news.content_status,
        extraction_method=news.extraction_method,
        event_cluster_id=news.event_cluster_id,
        chunk_count=chunk_count,
        extra=dict(news.extra or {}),
    )


@router.get("/{news_id}/related", response_model=RelatedNewsResponse)
def get_related_news(
    news_id: int,
    session: Session = Depends(get_db),
    limit: int = Query(5, ge=1, le=30),
) -> RelatedNewsResponse:
    news = session.get(News, news_id)
    if news is None:
        raise HTTPException(status_code=404, detail="News item not found")
    if news.event_cluster_id is None:
        return RelatedNewsResponse(items=[])
    rows = session.execute(
        select(News, Source)
        .join(Source, Source.id == News.source_id)
        .where(News.event_cluster_id == news.event_cluster_id, News.id != news_id)
        .order_by(desc(News.published_at).nullslast(), desc(News.ingested_at))
        .limit(limit)
    ).all()
    ids = [item.id for item, _ in rows]
    topics = _load_topics(session, ids)
    entities = _load_entities(session, ids)
    return RelatedNewsResponse(
        items=[_summary(item, source, topics.get(item.id, []), entities.get(item.id, [])) for item, source in rows]
    )
