"""Layer 3 preflight checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text

from jarvis.core.settings import get_settings
from jarvis.db.session import SyncSessionLocal


@dataclass(frozen=True, slots=True)
class RetrievalPreflightResult:
    """Result of checking Layer 3 dependencies."""

    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def run_retrieval_preflight(*, warm_models: bool = False) -> RetrievalPreflightResult:
    """Check Postgres, Redis, Qdrant and optionally model availability."""
    settings = get_settings()
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}

    try:
        with SyncSessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception as exc:
        checks["postgres"] = False
        errors["postgres"] = str(exc)

    try:
        from redis import Redis

        redis = Redis.from_url(settings.redis_url)
        redis.ping()
        checks["redis"] = True
    except Exception as exc:
        checks["redis"] = False
        errors["redis"] = str(exc)

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.qdrant_url)
        client.get_collection(settings.qdrant_collection_alias)
        checks["qdrant"] = True
    except Exception as exc:
        checks["qdrant"] = False
        errors["qdrant"] = str(exc)

    if warm_models:
        try:
            from jarvis.processing.services.embedding_runtime import encode_texts

            encode_texts(["Layer 3 retrieval preflight"])
            checks["embedding"] = True
        except Exception as exc:
            checks["embedding"] = False
            errors["embedding"] = str(exc)

        try:
            from jarvis.retrieval.services.reranking import _load_reranker

            checks["reranker"] = _load_reranker() is not None
            if not checks["reranker"]:
                errors["reranker"] = "reranker unavailable; neutral fallback will be used"
        except Exception as exc:
            checks["reranker"] = False
            errors["reranker"] = str(exc)

    return RetrievalPreflightResult(ok=all(checks.values()), checks=checks, errors=errors)
