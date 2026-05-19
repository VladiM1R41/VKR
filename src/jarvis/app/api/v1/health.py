"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import text

from jarvis.app.schemas.common import HealthResponse, ReadyResponse
from jarvis.core.settings import get_settings
from jarvis.db.session import SyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready() -> JSONResponse | ReadyResponse:
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        with SyncSessionLocal() as session:
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

    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    payload = ReadyResponse(status=status, checks=checks)
    if checks.get("postgres") != "ok":
        return JSONResponse(status_code=503, content=payload.model_dump())
    return payload

