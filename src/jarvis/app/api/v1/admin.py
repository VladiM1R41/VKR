"""Admin observability endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db
from jarvis.app.schemas.admin import (
    AdminGenerationStatsResponse,
    AdminOverviewResponse,
    AdminProcessingResponse,
    AdminSearchStatsResponse,
    AdminSourceItem,
    AdminSourcesResponse,
)
from jarvis.core.settings import get_settings
from jarvis.db.models import Chunk, GenerationLog, IngestionError, News, SearchLog, Source
from jarvis.processing.services.reconciliation import check_qdrant_consistency

router = APIRouter()


def _infra_checks(session: Session) -> dict[str, str]:
    settings = get_settings()
    checks: dict[str, str] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc.__class__.__name__}"
    try:
        Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"
    try:
        QdrantClient(url=settings.qdrant_url, timeout=2).get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        checks["qdrant"] = f"error: {exc.__class__.__name__}"
    return checks


@router.get("/overview", response_model=AdminOverviewResponse)
def overview(session: Session = Depends(get_db)) -> AdminOverviewResponse:
    recent_errors = session.scalars(
        select(IngestionError).order_by(desc(IngestionError.occurred_at)).limit(5)
    ).all()
    return AdminOverviewResponse(
        corpus={
            "news_total": session.scalar(select(func.count()).select_from(News)) or 0,
            "news_processed": session.scalar(select(func.count()).select_from(News).where(News.processed.is_(True))) or 0,
            "news_unprocessed": session.scalar(select(func.count()).select_from(News).where(News.processed.is_(False))) or 0,
            "sources_total": session.scalar(select(func.count()).select_from(Source)) or 0,
            "sources_active": session.scalar(select(func.count()).select_from(Source).where(Source.is_active.is_(True))) or 0,
            "chunks": session.scalar(select(func.count()).select_from(Chunk)) or 0,
            "search_logs": session.scalar(select(func.count()).select_from(SearchLog)) or 0,
            "generation_logs": session.scalar(select(func.count()).select_from(GenerationLog)) or 0,
        },
        infrastructure=_infra_checks(session),
        recent_errors=[
            {
                "id": error.id,
                "source_id": error.source_id,
                "type": error.error_type,
                "message": error.error_message[:300],
                "occurred_at": error.occurred_at,
            }
            for error in recent_errors
        ],
    )


@router.get("/sources", response_model=AdminSourcesResponse)
def sources(session: Session = Depends(get_db)) -> AdminSourcesResponse:
    rows = session.scalars(select(Source).order_by(Source.name)).all()
    return AdminSourcesResponse(
        items=[
            AdminSourceItem(
                id=row.id,
                name=row.name,
                type=row.type,
                is_active=row.is_active,
                health_status=row.health_status,
                consecutive_failures=row.consecutive_failures,
                parse_success_rate=row.parse_success_rate,
                extraction_success_rate=row.extraction_success_rate,
                last_crawled=row.last_crawled,
                last_error=row.last_error,
            )
            for row in rows
        ]
    )


@router.get("/processing", response_model=AdminProcessingResponse)
def processing(session: Session = Depends(get_db)) -> AdminProcessingResponse:
    try:
        report = check_qdrant_consistency()
        qdrant_report = {**asdict(report), "is_green": report.is_green}
    except Exception as exc:
        qdrant_report = {"status": "error", "error": str(exc)}
    return AdminProcessingResponse(
        processed=session.scalar(select(func.count()).select_from(News).where(News.processed.is_(True))) or 0,
        unprocessed=session.scalar(select(func.count()).select_from(News).where(News.processed.is_(False))) or 0,
        chunks=session.scalar(select(func.count()).select_from(Chunk)) or 0,
        qdrant=qdrant_report,
    )


@router.get("/search-stats", response_model=AdminSearchStatsResponse)
def search_stats(session: Session = Depends(get_db)) -> AdminSearchStatsResponse:
    rows = session.scalars(select(SearchLog).order_by(desc(SearchLog.created_at)).limit(20)).all()
    mode_rows = session.execute(select(SearchLog.retrieval_mode, func.count()).group_by(SearchLog.retrieval_mode)).all()
    return AdminSearchStatsResponse(
        total_searches=session.scalar(select(func.count()).select_from(SearchLog)) or 0,
        avg_latency_ms=session.scalar(select(func.avg(SearchLog.retrieval_time_ms))),
        cache_hit_count=session.scalar(select(func.count()).select_from(SearchLog).where(SearchLog.cache_hit.is_(True))) or 0,
        retrieval_modes={str(mode): int(count) for mode, count in mode_rows},
        recent_queries=[
            {
                "id": row.id,
                "query": row.query_text,
                "resolved_query": row.resolved_query,
                "latency_ms": row.retrieval_time_ms,
                "cache_hit": row.cache_hit,
                "retrieval_mode": row.retrieval_mode,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    )


@router.get("/generation-stats", response_model=AdminGenerationStatsResponse)
def generation_stats(session: Session = Depends(get_db)) -> AdminGenerationStatsResponse:
    rows = session.scalars(select(GenerationLog).order_by(desc(GenerationLog.created_at)).limit(20)).all()
    mode_rows = session.execute(select(GenerationLog.rag_mode, func.count()).group_by(GenerationLog.rag_mode)).all()
    confidence_rows = session.execute(select(GenerationLog.confidence, func.count()).group_by(GenerationLog.confidence)).all()
    return AdminGenerationStatsResponse(
        total_generations=session.scalar(select(func.count()).select_from(GenerationLog)) or 0,
        avg_latency_ms=session.scalar(select(func.avg(GenerationLog.latency_ms))),
        rag_modes={str(mode): int(count) for mode, count in mode_rows},
        confidence={str(confidence): int(count) for confidence, count in confidence_rows},
        recent_generations=[
            {
                "id": row.id,
                "query": row.query,
                "rag_mode": row.rag_mode,
                "model_name": row.model_name,
                "confidence": row.confidence,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    )
