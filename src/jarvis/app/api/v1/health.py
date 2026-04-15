"""GET /health и GET /ready — проверка состояния сервисов."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jarvis.core.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])
settings = get_settings()


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Живость сервиса",
    description="Всегда возвращает 200 OK. Используется для liveness probe.",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    summary="Готовность сервиса",
    description="Проверяет соединение с PostgreSQL, Redis и Qdrant. "
                "Возвращает 200 если все сервисы доступны, 503 если хотя бы один недоступен.",
)
def ready() -> JSONResponse:
    checks: dict[str, str] = {}

    # PostgreSQL
    try:
        from jarvis.db.session import SyncSessionLocal
        from sqlalchemy import text
        with SyncSessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        logger.warning("readiness check: postgres failed: %s", exc)
        checks["postgres"] = "error"

    # Redis
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("readiness check: redis failed: %s", exc)
        checks["redis"] = "error"

    # Qdrant
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url, timeout=3)
        client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        logger.warning("readiness check: qdrant failed: %s", exc)
        checks["qdrant"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=http_status,
        content=ReadyResponse(
            status="ok" if all_ok else "degraded",
            checks=checks,
        ).model_dump(),
    )
