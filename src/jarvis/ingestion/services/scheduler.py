"""Periodic scheduling helpers for Layer 1 source polling."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings
from jarvis.db.models import Source
from jarvis.db.session import SyncSessionLocal
from jarvis.ingestion.services.distributed_lock import is_collection_locked, mark_collection_pending


PRIORITY_ORDER = {
    "continuous": 0,
    "periodic": 1,
    "control": 2,
}

logger = logging.getLogger(__name__)


def compute_source_jitter_seconds(source: Source) -> int:
    """Stable per-cycle jitter based on source id and last crawl timestamp."""

    settings = get_settings()
    base_seconds = max(60, int(source.crawl_interval) * 60)
    max_jitter = int(base_seconds * settings.crawl_jitter_ratio)
    if max_jitter <= 0:
        return 0

    last_crawled_token = int(source.last_crawled.timestamp()) if source.last_crawled else 0
    seed = f"{source.id}:{last_crawled_token}:{base_seconds}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:8], "big") / float(2**64)
    return int(round((fraction * 2 - 1) * max_jitter))


def compute_next_due_at(source: Source) -> datetime:
    """Return next eligible poll timestamp for a source."""

    if source.last_crawled is None:
        return datetime.min.replace(tzinfo=timezone.utc)

    base_seconds = max(60, int(source.crawl_interval) * 60)
    jitter_seconds = compute_source_jitter_seconds(source)
    effective_delay = max(60, base_seconds + jitter_seconds)
    return source.last_crawled + timedelta(seconds=effective_delay)


def is_source_due(source: Source, now: datetime | None = None) -> bool:
    """Check whether the source should be polled now."""

    if not source.is_active or source.delivery_mode != "pull":
        return False

    now = now or datetime.now(timezone.utc)
    return compute_next_due_at(source) <= now


def _load_active_sources(source_name: str | None = None) -> list[Source]:
    with SyncSessionLocal() as session:
        stmt = select(Source).where(Source.is_active.is_(True)).order_by(Source.id.asc())
        if source_name:
            stmt = stmt.where(Source.name == source_name)
        return list(session.scalars(stmt).all())


def _enqueue_collect_source(source_name: str) -> None:
    """Enqueue one source discovery task without importing Celery at module import time."""

    from jarvis.ingestion.tasks.source_tasks import collect_source_task

    collect_source_task.apply_async(args=[source_name], queue="collector_queue")


async def dispatch_due_sources_once(source_name: str | None = None, dry_run: bool = False) -> dict:
    """Find due sources and enqueue collection tasks."""

    settings = get_settings()

    sources = _load_active_sources(source_name)
    now = datetime.now(timezone.utc)
    due_entries: list[dict[str, object]] = []

    for source in sorted(sources, key=lambda item: (PRIORITY_ORDER.get(item.priority, 99), item.id)):
        next_due_at = compute_next_due_at(source)
        if not is_source_due(source, now=now):
            continue

        if await is_collection_locked(source.id):
            due_entries.append(
                {
                    "source": source.name,
                    "source_id": source.id,
                    "priority": source.priority,
                    "next_due_at": next_due_at.isoformat(),
                    "scheduled": False,
                    "reason": "locked",
                }
            )
            continue

        if dry_run:
            due_entries.append(
                {
                    "source": source.name,
                    "source_id": source.id,
                    "priority": source.priority,
                    "next_due_at": next_due_at.isoformat(),
                    "scheduled": False,
                    "reason": "dry_run",
                }
            )
            continue

        pending_ttl = max(settings.source_lock_ttl_seconds, settings.source_budget_seconds + 60)
        pending_marked = await mark_collection_pending(source.id, pending_ttl)
        if not pending_marked:
            due_entries.append(
                {
                    "source": source.name,
                    "source_id": source.id,
                    "priority": source.priority,
                    "next_due_at": next_due_at.isoformat(),
                    "scheduled": False,
                    "reason": "already_pending",
                }
            )
            continue

        _enqueue_collect_source(source.name)
        due_entries.append(
            {
                "source": source.name,
                "source_id": source.id,
                "priority": source.priority,
                "next_due_at": next_due_at.isoformat(),
                "scheduled": True,
                "reason": "enqueued",
            }
        )

    result = {
        "checked_sources": len(sources),
        "due_sources": len(due_entries),
        "scheduled_count": sum(1 for entry in due_entries if entry["scheduled"]),
        "entries": due_entries,
    }
    log_level = logging.INFO if dry_run or result["scheduled_count"] > 0 else logging.DEBUG
    log_event(
        logger,
        log_level,
        "dispatch_due_sources_completed",
        checked_sources=result["checked_sources"],
        due_sources=result["due_sources"],
        scheduled_count=result["scheduled_count"],
        dry_run=dry_run,
        filtered_source=source_name,
    )
    return result


def run_dispatch_due_sources(source_name: str | None = None, dry_run: bool = False) -> dict:
    """Sync wrapper for CLI and Celery usage."""

    return asyncio.run(dispatch_due_sources_once(source_name=source_name, dry_run=dry_run))
