"""Digest endpoints over Layer 4 shortlist and Layer 5 generation."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from jarvis.app.api.v1.chat import _search_context
from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.digest import DigestGenerateRequest, DigestItemView, DigestListResponse, DigestResponse
from jarvis.db.models import Digest, DigestItem, News
from jarvis.generation.services.answer_generation_service import build_answer_generation_service
from jarvis.generation.tasks.tts_tasks import generate_digest_audio_task
from jarvis.personalization.services.digest_service import DigestOrchestrationService

router = APIRouter()


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


def _generate_digest(session: Session, user_id: int, request: DigestGenerateRequest) -> Digest:
    _, l4_response, _ = _search_context(session, query=request.query, limit=request.limit, user_id=user_id)
    shortlist = DigestOrchestrationService().build_shortlist(
        session,
        user_id=user_id,
        digest_type=request.digest_type,
        ranked_response=l4_response,
        limit=min(7, len(l4_response.results)),
    )
    if not shortlist.candidates:
        raise HTTPException(status_code=404, detail="No candidates for digest")
    text, generation_log_id = DigestOrchestrationService().generate_digest_text(
        session,
        shortlist,
        generation_service=build_answer_generation_service(),
    )
    digest = DigestOrchestrationService().persist_shortlist(
        session,
        shortlist=shortlist,
        content_text=text,
        generation_log_id=generation_log_id,
    )
    session.commit()
    session.refresh(digest)
    return digest


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
    if not request.force:
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
    if result.get("status") == "ok":
        session.refresh(digest)
        if digest.audio_path and Path(digest.audio_path).exists():
            return FileResponse(digest.audio_path, media_type="audio/wav")
    return JSONResponse(status_code=202, content={"status": result.get("status", "pending"), "detail": result})
