"""GET /analytics, /analytics/ablation, /analytics/search-stats — аналитика корпуса."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db
from jarvis.db.models import (
    Chunk,
    Entity,
    GenerationLog,
    News,
    NewsEntity,
    NewsTopic,
    SearchLog,
    SearchResult,
    Source,
    TermVocabulary,
    Topic,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class CorpusStatsOut(BaseModel):
    news_total: int
    news_processed: int
    news_last_hour: int
    news_last_day: int
    sources_active: int
    entities_total: int
    topics_total: int
    vocab_size: int
    chunks_total: int
    avg_chunks_per_article: float
    avg_entities_per_article: float


class AnalyticsOut(BaseModel):
    corpus: CorpusStatsOut
    generated_at: datetime


class AblationModeOut(BaseModel):
    rag_mode: str
    prompt_version: Optional[str]
    count: int
    avg_latency_ms: Optional[float]
    avg_confidence_high_pct: float


class AblationOut(BaseModel):
    modes: list[AblationModeOut]
    total_generations: int


class TopQueryOut(BaseModel):
    query: str
    count: int


class SearchStatsOut(BaseModel):
    total_searches: int
    avg_latency_ms: Optional[float]
    avg_results: Optional[float]
    top_queries: list[TopQueryOut]
    period_days: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=AnalyticsOut,
    summary="Статистика корпуса",
    description="Общая аналитика: количество новостей, источников, сущностей, "
                "размер словаря, средние показатели обработки.",
)
def get_analytics(db: Session = Depends(get_db)) -> AnalyticsOut:
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    news_total = db.scalar(select(func.count()).select_from(News)) or 0
    news_processed = db.scalar(
        select(func.count()).select_from(News).where(News.processed.is_(True))
    ) or 0
    news_last_hour = db.scalar(
        select(func.count()).select_from(News).where(News.ingested_at >= hour_ago)
    ) or 0
    news_last_day = db.scalar(
        select(func.count()).select_from(News).where(News.ingested_at >= day_ago)
    ) or 0
    sources_active = db.scalar(
        select(func.count()).select_from(Source).where(Source.is_active.is_(True))
    ) or 0
    entities_total = db.scalar(select(func.count()).select_from(Entity)) or 0
    topics_total = db.scalar(select(func.count()).select_from(Topic)) or 0
    vocab_size = db.scalar(select(func.count()).select_from(TermVocabulary)) or 0
    chunks_total = db.scalar(select(func.count()).select_from(Chunk)) or 0

    avg_chunks = round(chunks_total / max(news_processed, 1), 2)
    entity_links = db.scalar(select(func.count()).select_from(NewsEntity)) or 0
    avg_entities = round(entity_links / max(news_processed, 1), 2)

    corpus = CorpusStatsOut(
        news_total=int(news_total),
        news_processed=int(news_processed),
        news_last_hour=int(news_last_hour),
        news_last_day=int(news_last_day),
        sources_active=int(sources_active),
        entities_total=int(entities_total),
        topics_total=int(topics_total),
        vocab_size=int(vocab_size),
        chunks_total=int(chunks_total),
        avg_chunks_per_article=avg_chunks,
        avg_entities_per_article=avg_entities,
    )
    return AnalyticsOut(corpus=corpus, generated_at=now)


@router.get(
    "/ablation",
    response_model=AblationOut,
    summary="Ablation study RAG-режимов",
    description="Сравнение качества генерации по RAG-режимам на основе generation_logs: "
                "groundedness_score, latency_ms, доля HIGH-confidence ответов. "
                "Используется для исследовательской части ВКР.",
)
def get_ablation(db: Session = Depends(get_db)) -> AblationOut:
    total = db.scalar(select(func.count()).select_from(GenerationLog)) or 0

    import sqlalchemy
    rows = db.execute(
        select(
            GenerationLog.rag_mode,
            GenerationLog.prompt_version,
            func.count().label("cnt"),
            func.avg(GenerationLog.latency_ms).label("avg_latency"),
            func.avg(
                (GenerationLog.confidence == "HIGH").cast(sqlalchemy.Integer)
            ).label("high_pct"),
        )
        .group_by(GenerationLog.rag_mode, GenerationLog.prompt_version)
        .order_by(func.count().desc())
    ).all()

    modes = [
        AblationModeOut(
            rag_mode=str(r[0] or "standard"),
            prompt_version=r[1],
            count=int(r[2]),
            avg_latency_ms=round(float(r[3]), 1) if r[3] is not None else None,
            avg_confidence_high_pct=round(float(r[4] or 0), 3),
        )
        for r in rows
    ]
    return AblationOut(modes=modes, total_generations=int(total))


@router.get(
    "/search-stats",
    response_model=SearchStatsOut,
    summary="Статистика поиска",
    description="Популярные запросы, средняя латентность и click-through rate за период.",
)
def get_search_stats(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> SearchStatsOut:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    total = db.scalar(
        select(func.count()).select_from(SearchLog).where(SearchLog.created_at >= cutoff)
    ) or 0
    avg_latency = db.scalar(
        select(func.avg(SearchLog.retrieval_time_ms)).where(SearchLog.created_at >= cutoff)
    )
    avg_results = db.scalar(
        select(func.avg(SearchLog.num_results)).where(SearchLog.created_at >= cutoff)
    )

    top_raw = db.execute(
        select(SearchLog.query_text, func.count().label("cnt"))
        .where(SearchLog.created_at >= cutoff)
        .group_by(SearchLog.query_text)
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    top_queries = [TopQueryOut(query=str(r[0]), count=int(r[1])) for r in top_raw]

    return SearchStatsOut(
        total_searches=int(total),
        avg_latency_ms=round(float(avg_latency), 1) if avg_latency else None,
        avg_results=round(float(avg_results), 1) if avg_results else None,
        top_queries=top_queries,
        period_days=days,
    )
