"""Operational health metrics for Layer 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from jarvis.db.models import News
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.services.reconciliation import check_qdrant_consistency


@dataclass(frozen=True, slots=True)
class Layer2HealthMetrics:
    """Small production-facing Layer 2 health snapshot."""

    unprocessed_count: int
    oldest_pending_age_seconds: float | None
    processed_last_hour: int
    avg_processing_seconds_per_article: float | None
    chunks_without_qdrant_points: int
    qdrant_orphan_points: int


def collect_layer2_health_metrics() -> Layer2HealthMetrics:
    """Collect DB/Qdrant consistency and backlog metrics."""

    now = datetime.now(timezone.utc)
    with SyncSessionLocal() as session:
        unprocessed_count = int(
            session.scalar(select(func.count(News.id)).where(News.processed.is_(False))) or 0
        )
        oldest_pending = session.scalar(
            select(func.min(News.ingested_at)).where(News.processed.is_(False))
        )
        processed_extras = list(session.scalars(select(News.extra).where(News.processed.is_(True))).all())

    consistency = check_qdrant_consistency()
    oldest_pending_age_seconds = None
    if oldest_pending is not None:
        if oldest_pending.tzinfo is None:
            oldest_pending = oldest_pending.replace(tzinfo=timezone.utc)
        oldest_pending_age_seconds = max(0.0, (now - oldest_pending).total_seconds())

    processed_last_hour = 0
    processing_seconds_values: list[float] = []
    for extra in processed_extras:
        if not isinstance(extra, dict):
            continue
        processing = extra.get("processing")
        if not isinstance(processing, dict):
            continue
        processed_at_raw = processing.get("processed_at")
        if not processed_at_raw:
            continue
        try:
            processed_at = datetime.fromisoformat(str(processed_at_raw))
        except ValueError:
            continue
        if processed_at.tzinfo is None:
            processed_at = processed_at.replace(tzinfo=timezone.utc)
        if processed_at >= now - timedelta(hours=1):
            processed_last_hour += 1
            try:
                processing_seconds_values.append(float(processing.get("processing_seconds")))
            except (TypeError, ValueError):
                pass
    avg_processing_seconds = None
    if processing_seconds_values:
        avg_processing_seconds = round(
            sum(processing_seconds_values) / len(processing_seconds_values),
            3,
        )

    return Layer2HealthMetrics(
        unprocessed_count=unprocessed_count,
        oldest_pending_age_seconds=oldest_pending_age_seconds,
        processed_last_hour=processed_last_hour,
        avg_processing_seconds_per_article=avg_processing_seconds,
        chunks_without_qdrant_points=len(consistency.missing_point_ids),
        qdrant_orphan_points=len(consistency.orphan_point_ids),
    )
