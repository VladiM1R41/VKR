"""Layer 2 preflight checks for local and production-like runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text

from jarvis.core.settings import get_settings
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.services.embedding_runtime import encode_texts
from jarvis.processing.services.qdrant_index import QdrantIndexer


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Preflight outcome."""

    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _humanize_error(exc: Exception) -> str:
    message = str(exc)
    lower = message.lower()
    if "127.0.0.1" in message and "proxy" in lower:
        return (
            "Embedding model cannot be loaded because HTTP(S) proxy points to 127.0.0.1 "
            "and refuses connections. Clear/fix proxy env vars or pre-download BAAI/bge-m3 "
            "into the HuggingFace cache before running Layer 2."
        )
    if "huggingface.co" in lower:
        return (
            "Embedding model BAAI/bge-m3 is not available in local cache and HuggingFace "
            "download failed. Pre-download the model or run with working network/proxy."
        )
    return message


def run_layer2_preflight(*, check_model: bool = True) -> PreflightResult:
    """Check PostgreSQL, Redis, Qdrant and optionally embedding model readiness."""

    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    settings = get_settings()

    try:
        with SyncSessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception as exc:
        checks["postgres"] = False
        errors["postgres"] = str(exc)

    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url)
        client.ping()
        checks["redis"] = True
    except Exception as exc:
        checks["redis"] = False
        errors["redis"] = str(exc)

    try:
        QdrantIndexer()._client().get_collections()
        checks["qdrant"] = True
    except Exception as exc:
        checks["qdrant"] = False
        errors["qdrant"] = str(exc)

    if check_model:
        try:
            encode_texts(["Layer 2 embedding warmup"])
            checks["embedding_model"] = True
        except Exception as exc:
            checks["embedding_model"] = False
            errors["embedding_model"] = _humanize_error(exc)

    return PreflightResult(ok=all(checks.values()), checks=checks, errors=errors)
