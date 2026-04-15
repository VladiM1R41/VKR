"""CRUD /sources, GET /sources/health — управление источниками."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db
from jarvis.db.models import Source

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["Sources"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SourceOut(BaseModel):
    id: int
    name: str
    url: str
    source_type: str
    priority: Optional[str]
    trust_score: float
    is_active: bool
    health_status: Optional[str]
    last_success_at: Optional[datetime]
    consecutive_failures: int
    crawl_interval: Optional[int]


class SourceListOut(BaseModel):
    items: list[SourceOut]
    total: int


class SourceCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=5)
    source_type: str = Field("rss", description="rss | telegram | website")
    priority: str = Field("normal", description="low | normal | high | continuous")
    trust_score: float = Field(0.7, ge=0.0, le=1.0)
    config: dict[str, Any] = Field(default_factory=dict)


class SourceUpdateIn(BaseModel):
    priority: Optional[str] = None
    trust_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None
    config: Optional[dict[str, Any]] = None


class SourceHealthItemOut(BaseModel):
    id: int
    name: str
    health_status: str
    consecutive_failures: int
    last_success_at: Optional[datetime]
    last_error: Optional[str]


class SourceHealthOut(BaseModel):
    green: int
    yellow: int
    red: int
    unknown: int
    sources: list[SourceHealthItemOut]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _source_to_out(s: Source) -> SourceOut:
    return SourceOut(
        id=int(s.id),
        name=str(s.name),
        url=str(s.url),
        source_type=str(s.type),
        priority=s.priority,
        trust_score=float(s.trust_score or 0.7),
        is_active=bool(s.is_active),
        health_status=s.health_status,
        last_success_at=s.last_crawled,
        consecutive_failures=int(s.consecutive_failures or 0),
        crawl_interval=s.crawl_interval,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=SourceListOut,
    summary="Список источников",
    description="Возвращает все источники с текущим health-статусом.",
)
def list_sources(
    active_only: bool = True,
    db: Session = Depends(get_db),
) -> SourceListOut:
    stmt = select(Source)
    if active_only:
        stmt = stmt.where(Source.is_active.is_(True))
    stmt = stmt.order_by(Source.name)
    rows = db.scalars(stmt).all()
    total = db.scalar(select(func.count()).select_from(Source).where(
        Source.is_active.is_(True) if active_only else True
    )) or 0
    return SourceListOut(items=[_source_to_out(s) for s in rows], total=int(total))


@router.post(
    "",
    response_model=SourceOut,
    status_code=201,
    summary="Добавить источник",
    description="Создаёт новый RSS/Telegram/веб источник для сбора новостей.",
)
def create_source(body: SourceCreateIn, db: Session = Depends(get_db)) -> SourceOut:
    source = Source(
        name=body.name,
        url=body.url,
        source_type=body.source_type,
        priority=body.priority,
        trust_score=body.trust_score,
        config=body.config,
        is_active=True,
        consecutive_failures=0,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_to_out(source)


@router.put(
    "/{source_id}",
    response_model=SourceOut,
    summary="Обновить источник",
)
def update_source(
    source_id: int,
    body: SourceUpdateIn,
    db: Session = Depends(get_db),
) -> SourceOut:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    if body.priority is not None:
        source.priority = body.priority
    if body.trust_score is not None:
        source.trust_score = body.trust_score
    if body.is_active is not None:
        source.is_active = body.is_active
    if body.config is not None:
        source.config = body.config
    db.commit()
    db.refresh(source)
    return _source_to_out(source)


@router.delete(
    "/{source_id}",
    status_code=204,
    summary="Деактивировать источник",
    description="Soft-delete: устанавливает is_active=false, данные сохраняются.",
)
def delete_source(source_id: int, db: Session = Depends(get_db)) -> Response:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    source.is_active = False
    db.commit()
    return Response(status_code=204)


@router.get(
    "/health",
    response_model=SourceHealthOut,
    summary="Health-сводка источников",
    description="Показывает green/yellow/red распределение источников по health_status.",
)
def sources_health(db: Session = Depends(get_db)) -> SourceHealthOut:
    rows = db.scalars(select(Source).where(Source.is_active.is_(True))).all()
    counts: dict[str, int] = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
    items: list[SourceHealthItemOut] = []
    for s in rows:
        status = str(s.health_status or "unknown")
        counts[status if status in counts else "unknown"] += 1
        items.append(SourceHealthItemOut(
            id=int(s.id),
            name=str(s.name),
            health_status=status,
            consecutive_failures=int(s.consecutive_failures or 0),
            last_success_at=s.last_crawled,
            last_error=s.last_error,
        ))
    items.sort(key=lambda x: (x.health_status != "red", x.health_status != "yellow", x.name))
    return SourceHealthOut(**counts, sources=items)
