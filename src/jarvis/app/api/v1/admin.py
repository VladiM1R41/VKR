"""Admin observability endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from jarvis.app.dependencies import require_admin_user, get_db
from jarvis.app.schemas.admin import (
    AdminGenerationStatsResponse,
    AdminOverviewResponse,
    AdminProcessingResponse,
    AdminSearchStatsResponse,
    AdminSettingsResponse,
    AdminSourceItem,
    AdminSourcesResponse,
    AdminUserItem,
    AdminUsersResponse,
    AdminUserUpdateRequest,
)
from jarvis.core.settings import get_settings
from jarvis.db.models import (
    ChatSession,
    Chunk,
    Digest,
    GenerationLog,
    IngestionError,
    News,
    SearchLog,
    Source,
    User,
    UserInteraction,
)
from jarvis.processing.services.reconciliation import check_qdrant_consistency

router = APIRouter(dependencies=[Depends(require_admin_user)])


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


def _counts_by_user(session: Session, model: type, user_id_column) -> dict[int, int]:
    rows = session.execute(select(user_id_column, func.count()).select_from(model).group_by(user_id_column)).all()
    return {int(user_id): int(count) for user_id, count in rows if user_id is not None}


def _admin_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))) or 0


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


@router.get("/users", response_model=AdminUsersResponse)
def users(session: Session = Depends(get_db)) -> AdminUsersResponse:
    chat_counts = _counts_by_user(session, ChatSession, ChatSession.user_id)
    interaction_counts = _counts_by_user(session, UserInteraction, UserInteraction.user_id)
    digest_counts = _counts_by_user(session, Digest, Digest.user_id)
    search_counts = _counts_by_user(session, SearchLog, SearchLog.user_id)
    generation_counts = _counts_by_user(session, GenerationLog, GenerationLog.user_id)
    rows = session.scalars(select(User).order_by(User.id)).all()
    return AdminUsersResponse(
        total=len(rows),
        admin_count=sum(1 for row in rows if row.is_admin),
        items=[
            AdminUserItem(
                id=int(row.id),
                username=row.username,
                email=row.email,
                is_admin=bool(row.is_admin),
                has_password=bool(row.password_hash),
                created_at=row.created_at,
                last_active_at=row.last_active_at,
                chat_sessions=chat_counts.get(int(row.id), 0),
                interactions=interaction_counts.get(int(row.id), 0),
                digests=digest_counts.get(int(row.id), 0),
                search_logs=search_counts.get(int(row.id), 0),
                generation_logs=generation_counts.get(int(row.id), 0),
            )
            for row in rows
        ],
    )


@router.patch("/users/{user_id}", response_model=AdminUserItem)
def update_user(
    user_id: int,
    request: AdminUserUpdateRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> AdminUserItem:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if request.is_admin is not None and request.is_admin != user.is_admin:
        if request.is_admin is False:
            if int(user.id) == int(current_user.id):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own admin access.")
            if _admin_count(session) <= 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one admin user is required.")
        user.is_admin = request.is_admin
        session.flush()

    return AdminUserItem(
        id=int(user.id),
        username=user.username,
        email=user.email,
        is_admin=bool(user.is_admin),
        has_password=bool(user.password_hash),
        created_at=user.created_at,
        last_active_at=user.last_active_at,
    )


@router.get("/settings", response_model=AdminSettingsResponse)
def settings() -> AdminSettingsResponse:
    settings = get_settings()
    return AdminSettingsResponse(
        auth={
            "mode": settings.auth_mode,
            "jwt_enabled": settings.auth_mode == "jwt",
            "jwt_algorithm": settings.jwt_algorithm,
            "access_token_expire_minutes": settings.jwt_access_token_expire_minutes,
            "password_min_length": settings.auth_password_min_length,
        },
        runtime={
            "environment": settings.app_env,
            "debug": settings.app_debug,
            "log_level": settings.app_log_level,
            "postgres": f"{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
            "redis": f"{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
            "qdrant": settings.qdrant_url,
        },
        retrieval={
            "reranker_enabled": settings.reranker_enabled,
            "reranker_device": settings.reranker_device,
            "reranker_max_candidates": settings.reranker_max_candidates,
            "reranker_max_doc_chars": settings.reranker_max_doc_chars,
            "reranker_batch_size": settings.reranker_batch_size,
            "search_quality_signals_enabled": settings.search_quality_signals_enabled,
        },
        llm={
            "provider": settings.jarvis_llm_provider,
            "model": settings.jarvis_llm_model,
            "rag_mode": settings.jarvis_rag_mode,
            "timeout_sec": settings.jarvis_llm_timeout_sec,
            "max_input_tokens": settings.jarvis_llm_max_input_tokens,
            "max_output_tokens": settings.jarvis_llm_max_output_tokens,
            "digest_max_output_tokens": settings.jarvis_llm_digest_max_output_tokens,
            "temperature": settings.jarvis_llm_temperature,
            "tls_verify": settings.gigachat_tls_verify,
            "openrouter_base_url": settings.openrouter_base_url,
            "openrouter_site_url": settings.openrouter_site_url,
            "openrouter_app_name": settings.openrouter_app_name,
            "openrouter_api_key_configured": bool(settings.openrouter_api_key),
        },
        celery={
            "source_budget_seconds": settings.source_budget_seconds,
            "scheduler_tick_seconds": settings.scheduler_tick_seconds,
            "processing_batch_size": settings.processing_batch_size,
            "processing_tick_seconds": settings.processing_tick_seconds,
            "layer4_schedule_enabled": settings.celery_enable_layer4_schedule,
        },
    )
