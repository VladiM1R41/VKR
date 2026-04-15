"""POST /search, GET /search/suggest, GET /search/logs — поиск новостей."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db, get_default_user_id
from jarvis.db.models import SearchLog
from sqlalchemy import select

from jarvis.personalization.services.ranking_service import PersonalizedRankingService
from jarvis.retrieval.models.search_models import SearchFilters, SearchRequest
from jarvis.retrieval.services.search_service import SearchService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["Search"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class SearchFiltersIn(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    source_ids: Optional[list[int]] = None
    topics: Optional[list[str]] = None
    language: str = "ru"


class SearchIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Поисковый запрос")
    limit: int = Field(10, ge=1, le=50, description="Максимальное число результатов")
    filters: Optional[SearchFiltersIn] = None


class SearchResultOut(BaseModel):
    news_id: int
    chunk_id: str
    source_id: int
    source_name: str
    title: str
    snippet: str
    score: float
    personalized_score: float
    rerank_score: Optional[float] = None
    topics: list[str]
    entities: list[str]
    published_at: Optional[datetime]
    explanation: Optional[str]
    personalization_reasons: list[str]


class SearchOut(BaseModel):
    query: str
    corrected_query: Optional[str]
    intent: str
    total: int
    search_time_ms: float
    results: list[SearchResultOut]


class SuggestOut(BaseModel):
    suggestions: list[str]


class SearchLogOut(BaseModel):
    id: int
    query: str
    corrected_query: Optional[str]
    intent: Optional[str]
    total_results: Optional[int]
    search_time_ms: Optional[float]
    created_at: datetime


class SearchLogsOut(BaseModel):
    items: list[SearchLogOut]
    total: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=SearchOut,
    summary="Гибридный поиск новостей",
    description="Выполняет dense+sparse поиск в Qdrant с RRF-fusion, "
                "кросс-энкодерным реранкингом (BAAI/bge-reranker-v2-m3) и "
                "персонализированным перевзвешиванием (Layer 4).",
)
def search(
    body: SearchIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> SearchOut:
    filters = None
    if body.filters:
        filters = SearchFilters(
            date_from=body.filters.date_from,
            date_to=body.filters.date_to,
            source_ids=body.filters.source_ids,
            topics=body.filters.topics,
            language=body.filters.language,
        )

    search_service = SearchService()
    ranking_service = PersonalizedRankingService()

    request = SearchRequest(query=body.query, limit=body.limit, filters=filters)
    l3_response = search_service.search(request)
    l4_response = ranking_service.rerank(db, user_id=user_id, response=l3_response)

    results = [
        SearchResultOut(
            news_id=r.news_id,
            chunk_id=r.chunk_id or "",
            source_id=r.source_id,
            source_name=r.source_name,
            title=r.title,
            snippet=r.snippet,
            score=r.base_score,
            personalized_score=r.personalized_score,
            rerank_score=r.rerank_score,
            topics=r.topics,
            entities=r.entities,
            published_at=r.published_at,
            explanation=r.explanation,
            personalization_reasons=r.personalization_reasons,
        )
        for r in l4_response.results
    ]
    return SearchOut(
        query=l3_response.query,
        corrected_query=l3_response.corrected_query,
        intent=l3_response.intent,
        total=l4_response.total,
        search_time_ms=l3_response.search_time_ms,
        results=results,
    )


@router.get(
    "/suggest",
    response_model=SuggestOut,
    summary="Автодополнение поиска",
    description="Возвращает подсказки на основе словаря корпуса (term_vocabulary).",
)
def suggest(
    q: str = Query(..., min_length=1, max_length=100, description="Префикс запроса"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> SuggestOut:
    from jarvis.db.models import TermVocabulary
    rows = db.scalars(
        select(TermVocabulary.term)
        .where(TermVocabulary.term.ilike(f"{q}%"))
        .order_by(TermVocabulary.doc_freq.desc())
        .limit(limit)
    ).all()
    return SuggestOut(suggestions=list(rows))


@router.get(
    "/logs",
    response_model=SearchLogsOut,
    summary="История поисковых запросов",
    description="Последние поисковые запросы с метриками (latency, intent, total_results).",
)
def search_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> SearchLogsOut:
    from sqlalchemy import func
    total = db.scalar(select(func.count()).select_from(SearchLog)) or 0
    rows = db.scalars(
        select(SearchLog).order_by(SearchLog.created_at.desc()).limit(limit).offset(offset)
    ).all()
    items = [
        SearchLogOut(
            id=int(row.id),
            query=str(row.query),
            corrected_query=row.corrected_query,
            intent=row.intent,
            total_results=row.total_results,
            search_time_ms=row.search_time_ms,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return SearchLogsOut(items=items, total=int(total))
