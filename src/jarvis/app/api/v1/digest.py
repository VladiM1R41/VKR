"""GET /digest, /digest/audio, /digests."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db, get_default_user_id
from jarvis.db.models import Digest, DigestItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digest", tags=["Digest"])

_DIGEST_TYPE_ALIASES = {
    "daily": "morning",
    "breaking": "on_demand",
    "analytics": "weekly",
    "morning": "morning",
    "evening": "evening",
    "weekly": "weekly",
    "on_demand": "on_demand",
}


class DigestOut(BaseModel):
    digest_id: int
    digest_type: str
    content_text: str
    item_count: int
    generated_at: datetime
    audio_url: str | None = None


class DigestListItemOut(BaseModel):
    digest_id: int
    digest_type: str
    item_count: int
    generated_at: datetime
    has_audio: bool


class DigestListOut(BaseModel):
    items: list[DigestListItemOut]
    total: int


def _normalize_digest_type(digest_type: str) -> str:
    normalized = _DIGEST_TYPE_ALIASES.get(digest_type, digest_type)
    if normalized not in {"morning", "evening", "weekly", "on_demand"}:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый digest_type: {digest_type}")
    return normalized


def _count_items(db: Session, digest_id: int) -> int:
    return int(
        db.scalar(select(func.count()).select_from(DigestItem).where(DigestItem.digest_id == digest_id)) or 0
    )


def _build_digest(user_id: int, digest_type: str, db: Session) -> Digest:
    """Build and persist a fresh digest via the current Layer 4 -> 5 pipeline."""
    from jarvis.generation.services import AnswerGenerationService, GenerationConfig
    from jarvis.generation.services.providers.factory import build_primary_provider
    from jarvis.personalization.services.digest_service import DigestOrchestrationService
    from jarvis.personalization.services.ranking_service import PersonalizedRankingService
    from jarvis.retrieval.models.search_models import SearchRequest
    from jarvis.retrieval.services.search_service import SearchService

    search_service = SearchService()
    l3_response = search_service.search(SearchRequest(query="главные новости сегодня", limit=20))

    ranking_service = PersonalizedRankingService()
    l4_response = ranking_service.rerank(db, user_id=user_id, response=l3_response)

    digest_service = DigestOrchestrationService()
    shortlist = digest_service.build_shortlist(
        db,
        user_id=user_id,
        digest_type=digest_type,
        ranked_response=l4_response,
        limit=5,
    )
    if not shortlist.candidates:
        raise RuntimeError("Не удалось собрать shortlist для дайджеста")

    generation_service = AnswerGenerationService(
        provider=build_primary_provider(),
        config=GenerationConfig(),
    )
    digest_text, generation_log_id = digest_service.generate_digest_text(
        db,
        shortlist=shortlist,
        generation_service=generation_service,
        continuity_context="",
    )
    return digest_service.persist_shortlist(
        db,
        shortlist=shortlist,
        content_text=digest_text,
        generation_log_id=generation_log_id,
    )


@router.get("", response_model=DigestOut, summary="Текущий дайджест")
def get_digest(
    digest_type: str = Query(
        "daily",
        description="daily / breaking / analytics / morning / evening / weekly / on_demand",
    ),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> DigestOut:
    requested_type = digest_type
    digest_type = _normalize_digest_type(digest_type)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    existing = db.scalar(
        select(Digest)
        .where(
            Digest.user_id == user_id,
            Digest.digest_type == digest_type,
            Digest.generated_at >= today_start,
        )
        .order_by(Digest.generated_at.desc())
    )

    if existing is None or not existing.content_text:
        try:
            existing = _build_digest(user_id, digest_type, db)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Ошибка генерации дайджеста: %s", exc)
            raise HTTPException(status_code=503, detail=f"Ошибка генерации дайджеста: {exc}")

    return DigestOut(
        digest_id=int(existing.id),
        digest_type=requested_type,
        content_text=str(existing.content_text or ""),
        item_count=_count_items(db, int(existing.id)),
        generated_at=existing.generated_at,
        audio_url=existing.audio_path if existing.audio_path else None,
    )


@router.get("/audio", summary="Аудио-версия дайджеста")
def get_digest_audio(
    digest_id: int = Query(..., description="ID дайджеста"),
    db: Session = Depends(get_db),
) -> object:
    digest = db.get(Digest, digest_id)
    if digest is None:
        raise HTTPException(status_code=404, detail="Дайджест не найден")
    if digest.audio_path and os.path.exists(digest.audio_path):
        return FileResponse(digest.audio_path, media_type="audio/mpeg")

    from jarvis.generation.tasks.tts_tasks import generate_digest_audio_task

    generate_digest_audio_task.delay(digest_id)
    return {"status": "accepted", "message": "Генерация аудио запущена", "digest_id": digest_id}


@router.get("s", response_model=DigestListOut, summary="Архив дайджестов")
def list_digests(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> DigestListOut:
    total = int(db.scalar(select(func.count()).select_from(Digest).where(Digest.user_id == user_id)) or 0)
    rows = db.scalars(
        select(Digest)
        .where(Digest.user_id == user_id)
        .order_by(Digest.generated_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        DigestListItemOut(
            digest_id=int(row.id),
            digest_type=str(row.digest_type),
            item_count=_count_items(db, int(row.id)),
            generated_at=row.generated_at,
            has_audio=bool(row.audio_path),
        )
        for row in rows
    ]
    return DigestListOut(items=items, total=total)
