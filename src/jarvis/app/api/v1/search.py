"""Search endpoints over Layer 3 and Layer 4."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.search import (
    SearchApiRequest,
    SearchApiResponse,
    SearchApiResult,
    SearchLogItem,
    SearchLogsResponse,
    SearchSuggestionResponse,
)
from jarvis.db.models import SearchLog, TermVocabulary
from jarvis.personalization.services.pipeline_service import PersonalizationPipelineService
from jarvis.retrieval.models.search_models import SearchRequest
from jarvis.retrieval.services.search_service import SearchService

router = APIRouter()


@router.post("", response_model=SearchApiResponse)
def search(
    request: SearchApiRequest,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> SearchApiResponse:
    """Run objective Layer 3 search and Layer 4 personalization/diversity."""
    l3_request = SearchRequest(query=request.query, limit=request.limit, filters=request.filters)
    l3_response = SearchService().search(l3_request, user_id=str(user_id))
    l4_response = PersonalizationPipelineService().personalize(session, user_id=user_id, response=l3_response)
    l3_by_news = {item.news_id: item for item in l3_response.results}

    results: list[SearchApiResult] = []
    for item in l4_response.results:
        original = l3_by_news.get(item.news_id)
        results.append(
            SearchApiResult(
                news_id=item.news_id,
                source_id=item.source_id,
                source_name=item.source_name,
                title=item.title,
                snippet=item.snippet,
                base_score=item.base_score,
                personalized_score=item.personalized_score,
                retrieval_mode=original.retrieval_mode if original else None,
                rerank_score=item.rerank_score,
                trust_score=item.trust_score,
                content_grade=item.content_grade,
                information_type=item.information_type,
                urgency=item.urgency,
                event_cluster_id=item.event_cluster_id,
                published_at=item.published_at,
                topics=item.topics,
                entities=item.entities,
                explanation=item.explanation,
                personalization_reasons=item.personalization_reasons,
            )
        )

    return SearchApiResponse(
        query=l4_response.query,
        corrected_query=l4_response.corrected_query,
        intent=l4_response.intent,
        total=l4_response.total,
        search_time_ms=l3_response.search_time_ms,
        results=results,
    )


@router.get("/suggest", response_model=SearchSuggestionResponse)
def suggest(
    query: str | None = Query(None, min_length=1, max_length=100),
    q: str | None = Query(None, min_length=1, max_length=100),
    limit: int = Query(8, ge=1, le=20),
    session: Session = Depends(get_db),
) -> SearchSuggestionResponse:
    raw_query = query or q
    if raw_query is None:
        raise HTTPException(status_code=422, detail="query is required")

    pattern = f"{raw_query.strip().lower()}%"
    terms = session.scalars(
        select(TermVocabulary.term)
        .where(func.lower(TermVocabulary.term).like(pattern))
        .order_by(TermVocabulary.doc_frequency.desc(), TermVocabulary.collection_frequency.desc())
        .limit(limit)
    ).all()
    return SearchSuggestionResponse(suggestions=[str(term) for term in terms])


@router.get("/logs", response_model=SearchLogsResponse)
def search_logs(
    session: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SearchLogsResponse:
    total = session.scalar(select(func.count()).select_from(SearchLog)) or 0
    rows = session.scalars(
        select(SearchLog).order_by(desc(SearchLog.created_at)).limit(limit).offset(offset)
    ).all()
    return SearchLogsResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            SearchLogItem(
                id=row.id,
                query_text=row.query_text,
                resolved_query=row.resolved_query,
                intent=row.intent,
                num_results=row.num_results,
                retrieval_time_ms=row.retrieval_time_ms,
                cache_hit=row.cache_hit,
                retrieval_mode=row.retrieval_mode,
                top_result_ids=list(row.top_result_ids or []),
                created_at=row.created_at,
            )
            for row in rows
        ],
    )
