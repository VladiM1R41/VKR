"""Digest endpoints over Layer 4 shortlist and Layer 5 generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from jarvis.app.api.v1.chat import _search_context
from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.digest import DigestGenerateRequest, DigestItemView, DigestListResponse, DigestResponse
from jarvis.db.models import Digest, DigestItem, News, User
from jarvis.generation.services.answer_generation_service import build_answer_generation_service
from jarvis.generation.services.providers.base import LLMProviderError
from jarvis.generation.tasks.tts_tasks import generate_digest_audio_task
from jarvis.personalization.services.digest_service import DigestOrchestrationService
from jarvis.retrieval.models.search_models import SearchFilters

router = APIRouter()

_DEFAULT_BIG_DIGEST_LIMIT = 40
_DEFAULT_DIGEST_QUERY = str(DigestGenerateRequest.model_fields["query"].default)


def _digest_response(session: Session, digest: Digest) -> DigestResponse:
    rows = session.execute(
        select(DigestItem, News.title, News.url)
        .join(News, News.id == DigestItem.news_id)
        .where(DigestItem.digest_id == digest.id)
        .order_by(DigestItem.position)
    ).all()
    return DigestResponse(
        id=digest.id,
        digest_type=digest.digest_type,
        content_text=digest.content_text,
        news_count=digest.news_count,
        topics_covered=list(digest.topics_covered or []),
        generation_log_id=digest.generation_log_id,
        generated_at=digest.generated_at,
        audio_path=digest.audio_path,
        items=[
            DigestItemView(news_id=item.news_id, position=item.position, snippet=item.snippet, title=title, url=url)
            for item, title, url in rows
        ],
    )


def _can_reuse_existing_digest(request: DigestGenerateRequest) -> bool:
    """Reuse cached latest digest only for the default digest request."""
    return (
        not request.force
        and request.query == _DEFAULT_DIGEST_QUERY
        and request.limit == _DEFAULT_BIG_DIGEST_LIMIT
        and request.digest_style is None
        and not request.topics
        and request.period_hours is None
    )


def _resolve_digest_style(session: Session, user_id: int, request: DigestGenerateRequest) -> str | None:
    if request.digest_style:
        return request.digest_style
    user = session.get(User, user_id)
    settings = dict(user.settings or {}) if user is not None else {}
    style = str(settings.get("digest_style") or "").strip().lower()
    return style if style in {"brief", "detailed", "analytical", "editorial"} else None


def _generate_digest(session: Session, user_id: int, request: DigestGenerateRequest) -> Digest:
    search_limit = max(request.limit, _DEFAULT_BIG_DIGEST_LIMIT)
    query = _digest_search_query(request)
    filters = _digest_search_filters(request)
    _, l4_response, _ = _search_context(
        session,
        query=query,
        limit=search_limit,
        user_id=user_id,
        filters=filters,
    )
    shortlist = DigestOrchestrationService().build_shortlist(
        session,
        user_id=user_id,
        digest_type=request.digest_type,
        ranked_response=l4_response,
        limit=min(request.limit, len(l4_response.results)),
    )
    if request.topics:
        _restrict_shortlist_topics(shortlist, request.topics)
    if not shortlist.candidates:
        raise HTTPException(status_code=404, detail="No candidates for digest")
    try:
        text, generation_log_id = DigestOrchestrationService().generate_digest_text(
            session,
            shortlist,
            generation_service=build_answer_generation_service(),
            digest_style=_resolve_digest_style(session, user_id, request),
        )
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    digest = DigestOrchestrationService().persist_shortlist(
        session,
        shortlist=shortlist,
        content_text=text,
        generation_log_id=generation_log_id,
    )
    session.commit()
    session.refresh(digest)
    return digest


def _digest_search_query(request: DigestGenerateRequest) -> str:
    topics = [topic.strip() for topic in request.topics if topic.strip()]
    return ", ".join(topics) if topics else request.query


def _digest_search_filters(request: DigestGenerateRequest) -> SearchFilters | None:
    if not request.topics and request.period_hours is None:
        return None
    date_from = None
    if request.period_hours is not None:
        date_from = datetime.now(UTC) - timedelta(hours=request.period_hours)
    return SearchFilters(
        topics=list(request.topics) or None,
        date_from=date_from,
        content_grade_max=5,
    )


def _restrict_shortlist_topics(shortlist, selected_topics: list[str]) -> None:
    selected = {topic.strip() for topic in selected_topics if topic.strip()}
    if not selected:
        return
    for candidate in shortlist.candidates:
        filtered = [topic for topic in candidate.topics if topic in selected]
        candidate.topics = filtered or list(selected)[:1]
    shortlist.topics_covered = sorted(
        {topic for candidate in shortlist.candidates for topic in candidate.topics if topic in selected}
    )


@router.get("/api/v1/digest", response_model=DigestResponse)
def get_digest(
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    digest_type: str = Query("on_demand", pattern="^(morning|evening|weekly|on_demand)$"),
) -> DigestResponse:
    digest = session.scalar(
        select(Digest)
        .where(Digest.user_id == user_id, Digest.digest_type == digest_type)
        .order_by(desc(Digest.generated_at))
        .limit(1)
    )
    if digest is None:
        digest = _generate_digest(session, user_id, DigestGenerateRequest(digest_type=digest_type))
    return _digest_response(session, digest)


@router.post("/api/v1/digest/generate", response_model=DigestResponse)
def generate_digest(
    request: DigestGenerateRequest,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> DigestResponse:
    if _can_reuse_existing_digest(request):
        existing = session.scalar(
            select(Digest)
            .where(Digest.user_id == user_id, Digest.digest_type == request.digest_type)
            .order_by(desc(Digest.generated_at))
            .limit(1)
        )
        if existing is not None:
            return _digest_response(session, existing)
    return _digest_response(session, _generate_digest(session, user_id, request))


@router.get("/api/v1/digests", response_model=DigestListResponse)
def list_digests(
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> DigestListResponse:
    total = session.scalar(select(func.count()).select_from(Digest).where(Digest.user_id == user_id)) or 0
    rows = session.scalars(
        select(Digest)
        .where(Digest.user_id == user_id)
        .order_by(desc(Digest.generated_at))
        .limit(limit)
        .offset(offset)
    ).all()
    return DigestListResponse(
        items=[_digest_response(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/api/v1/digest/audio")
def digest_audio(
    digest_id: int,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    digest = session.scalar(select(Digest).where(Digest.id == digest_id, Digest.user_id == user_id))
    if digest is None:
        raise HTTPException(status_code=404, detail="Digest not found")
    if digest.audio_path and Path(digest.audio_path).exists():
        return FileResponse(digest.audio_path, media_type="audio/wav")
    result = generate_digest_audio_task.run(digest_id)
    if result.get("status") == "success":
        session.refresh(digest)
        if digest.audio_path and Path(digest.audio_path).exists():
            return FileResponse(digest.audio_path, media_type="audio/wav")
    return JSONResponse(status_code=202, content={"status": result.get("status", "pending"), "detail": result})
