"""High-level orchestration for collecting a single source."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging

import httpx
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from jarvis.db.models import IngestionError, IngestionRun, News, NewsRaw, Source
from jarvis.db.models.ingestion_run import DISCOVERY_RUN_KIND
from jarvis.db.session import SyncSessionLocal
from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings
from jarvis.ingestion.collectors.dispatcher import CollectorDispatcher
from jarvis.ingestion.services.distributed_lock import (
    acquire_collection_lock,
    clear_collection_pending,
    clear_enrichment_pending,
    mark_enrichment_pending,
    request_enrichment_rerun,
)
from jarvis.ingestion.services.health import refresh_source_health


LOW_THRESHOLD = 1000
HIGH_THRESHOLD = 5000
CRITICAL_THRESHOLD = 10000
SOURCE_BUDGET_SECONDS = get_settings().source_budget_seconds
logger = logging.getLogger(__name__)


def _load_source_by_name(name: str) -> Source | None:
    with SyncSessionLocal() as session:
        return session.scalar(select(Source).where(Source.name == name))


def _load_known_canonical_urls(source_id: int, lookback_hours: int = 24) -> set[str]:
    since_dt = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    with SyncSessionLocal() as session:
        stmt = select(News.canonical_url).where(
            News.source_id == source_id,
            News.ingested_at >= since_dt,
        )
        return {row[0] for row in session.execute(stmt) if row[0]}


def _check_backpressure(source: Source) -> dict[str, int | str] | None:
    with SyncSessionLocal() as session:
        unprocessed_count = session.scalar(
            select(func.count()).select_from(News).where(News.processed.is_(False))
        )

    if unprocessed_count is None or unprocessed_count < LOW_THRESHOLD:
        return None

    if unprocessed_count < HIGH_THRESHOLD:
        return {
            "decision": "warn",
            "unprocessed_count": int(unprocessed_count),
        }

    if unprocessed_count < CRITICAL_THRESHOLD:
        if source.priority == "control":
            return {
                "decision": "skip",
                "unprocessed_count": int(unprocessed_count),
                "reason": "backpressure_control_skip",
            }
        return {
            "decision": "warn",
            "unprocessed_count": int(unprocessed_count),
        }

    if source.priority != "continuous" and source.trust_score < 0.85:
        return {
            "decision": "skip",
            "unprocessed_count": int(unprocessed_count),
            "reason": "circuit_breaker_open",
        }

    return {
        "decision": "warn",
        "unprocessed_count": int(unprocessed_count),
    }


def _start_run(source_id: int, *, run_kind: str = DISCOVERY_RUN_KIND) -> int:
    with SyncSessionLocal() as session:
        run = IngestionRun(source_id=source_id, run_kind=run_kind, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


def _finalize_run(
    *,
    run_id: int,
    source_id: int,
    status: str,
    items_total: int,
    items_new: int,
    items_duplicate: int,
    items_failed: int,
    http_status: int | None,
    response_bytes: int | None,
    parse_errors_count: int = 0,
    http_errors_count: int = 0,
    sent_etag: str | None = None,
    sent_if_modified_since: str | None = None,
    received_etag: str | None = None,
    received_last_modified: str | None = None,
    received_last_build_date: str | None = None,
) -> None:
    duration_seconds: float | None = None
    source_name: str | None = None
    with SyncSessionLocal() as session:
        run = session.get(IngestionRun, run_id)
        source = session.get(Source, source_id)
        if run is None or source is None:
            return

        finished_at = datetime.now(timezone.utc)
        run.status = status
        run.items_total = items_total
        run.items_new = items_new
        run.items_duplicate = items_duplicate
        run.items_failed = items_failed
        run.parse_errors_count = parse_errors_count
        run.http_errors_count = http_errors_count
        run.http_status = http_status
        run.response_bytes = response_bytes
        run.sent_etag = sent_etag
        run.sent_if_modified_since = sent_if_modified_since
        run.received_etag = received_etag
        run.received_last_modified = received_last_modified
        run.finished_at = finished_at
        duration_seconds = (finished_at - run.started_at).total_seconds()
        run.duration_seconds = duration_seconds

        source.last_run_id = run.id
        source.last_crawled = finished_at
        source_name = source.name
        if status in {"success", "partial", "skipped_304"}:
            source.error_count = 0

        config = dict(source.config or {})
        if received_etag:
            config["etag_value"] = received_etag
        if received_last_modified:
            config["last_modified_value"] = received_last_modified
        if received_last_build_date:
            config["last_build_date_value"] = received_last_build_date
        if config != (source.config or {}):
            source.config = config

        session.commit()

    refresh_source_health(source_id)
    log_level = logging.INFO
    if status in {"failed", "timeout"}:
        log_level = logging.ERROR
    elif status == "partial":
        log_level = logging.WARNING
    log_event(
        logger,
        log_level,
        "source_run_completed",
        source_id=source_id,
        source_name=source_name,
        run_id=run_id,
        run_kind=DISCOVERY_RUN_KIND,
        status=status,
        items_total=items_total,
        items_new=items_new,
        items_duplicate=items_duplicate,
        items_failed=items_failed,
        parse_errors_count=parse_errors_count,
        http_errors_count=http_errors_count,
        http_status=http_status,
        response_bytes=response_bytes,
        duration_seconds=duration_seconds,
    )


def _log_run_error(
    run_id: int,
    source_id: int,
    error_type: str,
    error_message: str,
    *,
    item_url: str | None = None,
    http_status: int | None = None,
    mark_run_failed: bool = True,
    increment_source_error: bool = True,
) -> None:
    with SyncSessionLocal() as session:
        session.add(
            IngestionError(
                run_id=run_id,
                source_id=source_id,
                error_type=error_type,
                error_message=error_message,
                item_url=item_url,
                http_status=http_status,
            )
        )
        run = session.get(IngestionRun, run_id)
        source = session.get(Source, source_id)
        if run is not None and mark_run_failed:
            run.status = "failed"
        if source is not None and increment_source_error:
            source.error_count = (source.error_count or 0) + 1
            source.last_error = error_message
        session.commit()
    log_event(
        logger,
        logging.ERROR,
        "source_run_error",
        source_id=source_id,
        run_id=run_id,
        run_kind=DISCOVERY_RUN_KIND,
        error_type=error_type,
        error_message=error_message,
        item_url=item_url,
        http_status=http_status,
    )


def _log_item_errors(run_id: int, source_id: int, item_errors: list[dict[str, str | int | None]]) -> None:
    if not item_errors:
        return

    with SyncSessionLocal() as session:
        for item_error in item_errors:
            session.add(
                IngestionError(
                    run_id=run_id,
                    source_id=source_id,
                    error_type=str(item_error["error_type"]),
                    error_message=str(item_error["error_message"]),
                    item_url=item_error.get("item_url"),  # type: ignore[arg-type]
                    http_status=item_error.get("http_status"),  # type: ignore[arg-type]
                )
            )
        session.commit()
    for item_error in item_errors:
        log_event(
            logger,
            logging.WARNING,
            "item_processing_failed",
            source_id=source_id,
            run_id=run_id,
            run_kind=DISCOVERY_RUN_KIND,
            error_type=str(item_error["error_type"]),
            error_message=str(item_error["error_message"]),
            item_url=item_error.get("item_url"),
            http_status=item_error.get("http_status"),
        )


def _source_uses_html_enrichment(source: Source) -> bool:
    method = str((source.config or {}).get("full_text_method") or "")
    return method.startswith("html_")


async def _enqueue_html_enrichment(source: Source, limit: int) -> bool:
    from jarvis.ingestion.tasks.enrichment_tasks import enrich_source_pending_task

    settings = get_settings()
    pending_ttl = max(settings.source_lock_ttl_seconds, settings.source_budget_seconds + 60)
    pending_marked = await mark_enrichment_pending(source.id, pending_ttl)
    if not pending_marked:
        await request_enrichment_rerun(source.id, pending_ttl)
        return False

    try:
        enrich_source_pending_task.apply_async(args=[source.name, limit], queue="enrichment_queue")
    except Exception:
        await clear_enrichment_pending(source.id)
        raise

    return True


def _persist_articles(run_id: int, source_id: int, articles: list) -> tuple[list[int], int, int]:
    inserted_ids: list[int] = []
    duplicates = 0
    failures = 0

    with SyncSessionLocal() as session:
        for article in articles:
            try:
                stmt = (
                    insert(News)
                    .values(
                        url=article.url,
                        canonical_url=article.canonical_url,
                        title=article.title,
                        content=article.content,
                        snippet_lead=article.snippet_lead,
                        published_at=article.published_at,
                        source_id=article.source_id,
                        ingestion_run_id=run_id,
                        channel_type=article.channel_type,
                        information_type=article.information_type,
                        content_type=article.content_type,
                        language=article.language,
                        title_hash=article.title_hash,
                        urgency=article.urgency,
                        is_uncertain=article.is_uncertain,
                        content_status=article.content_status,
                        extraction_method=article.extraction_method,
                        raw_pub_date=article.raw_pub_date,
                        parser_version=article.parser_version,
                        date_inferred=article.date_inferred,
                        extra=article.extra,
                    )
                    .on_conflict_do_nothing(index_elements=["canonical_url"])
                    .returning(News.id)
                )
                news_id = session.execute(stmt).scalar_one_or_none()
                if news_id is None:
                    duplicates += 1
                    session.commit()
                    continue

                session.execute(
                    update(News)
                    .where(News.id == news_id)
                    .values(event_cluster_id=news_id)
                )

                if article.raw_content:
                    raw_stmt = insert(NewsRaw).values(
                        news_id=news_id,
                        raw_content=article.raw_content,
                        raw_format=article.raw_format,
                        parser_version=article.parser_version,
                    )
                    raw_stmt = raw_stmt.on_conflict_do_update(
                        index_elements=["news_id"],
                        set_={
                            "raw_content": article.raw_content,
                            "raw_format": article.raw_format,
                            "parser_version": article.parser_version,
                        },
                    )
                    session.execute(raw_stmt)

                session.commit()
                inserted_ids.append(int(news_id))
            except IntegrityError as exc:
                session.rollback()
                failures += 1
                _log_run_error(
                    run_id,
                    source_id,
                    "db_constraint",
                    str(exc.orig) if exc.orig else str(exc),
                    item_url=article.canonical_url,
                    mark_run_failed=False,
                    increment_source_error=False,
                )
            except SQLAlchemyError as exc:
                session.rollback()
                failures += 1
                _log_run_error(
                    run_id,
                    source_id,
                    "db_constraint",
                    str(exc),
                    item_url=article.canonical_url,
                    mark_run_failed=False,
                    increment_source_error=False,
                )

    return inserted_ids, duplicates, failures


def _classify_source_exception(exc: Exception) -> tuple[str, int | None]:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return "http_429", status
        if 400 <= status < 500:
            return "http_4xx", status
        if 500 <= status < 600:
            return "http_5xx", status
        return "unknown", status

    if isinstance(exc, (httpx.TimeoutException, httpx.RequestError)):
        return "network", None

    if isinstance(exc, ValueError):
        return "rss_parse", None

    return "unknown", None


async def collect_source_once(source_name: str) -> dict:
    """Collect one source and persist minimal news rows."""
    source = _load_source_by_name(source_name)
    if source is None:
        raise ValueError(f"Unknown source: {source_name}")

    try:
        async with acquire_collection_lock(source.id) as lock_acquired:
            if not lock_acquired:
                log_event(
                    logger,
                    logging.DEBUG,
                    "source_run_skipped_locked",
                    source_id=source.id,
                    source_name=source.name,
                )
                return {
                    "source": source.name,
                    "status": "skipped_locked",
                    "run_id": None,
                }

            backpressure = _check_backpressure(source)
            if backpressure and backpressure.get("decision") == "skip":
                log_event(
                    logger,
                    logging.WARNING,
                    "source_run_skipped_backpressure",
                    source_id=source.id,
                    source_name=source.name,
                    reason=str(backpressure.get("reason") or "skipped"),
                    unprocessed_count=int(backpressure["unprocessed_count"]),
                )
                return {
                    "source": source.name,
                    "status": str(backpressure.get("reason") or "skipped"),
                    "run_id": None,
                    "unprocessed_count": int(backpressure["unprocessed_count"]),
                }

            run_id = _start_run(source.id)

            try:
                known_canonical_urls = _load_known_canonical_urls(source.id)
                async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                    collector = CollectorDispatcher.get_collector(
                        source,
                        client,
                        known_canonical_urls=known_canonical_urls,
                    )
                    articles = await asyncio.wait_for(
                        collector.collect(),
                        timeout=SOURCE_BUDGET_SECONDS,
                    )

                if getattr(collector, "last_was_not_modified", False):
                    _finalize_run(
                        run_id=run_id,
                        source_id=source.id,
                        status="skipped_304",
                        items_total=0,
                        items_new=0,
                        items_duplicate=0,
                        items_failed=0,
                        http_status=getattr(collector, "last_http_status", None),
                        response_bytes=getattr(collector, "last_response_bytes", None),
                        sent_etag=getattr(collector, "last_sent_etag", None),
                        sent_if_modified_since=getattr(collector, "last_sent_if_modified_since", None),
                        received_etag=getattr(collector, "last_received_etag", None),
                        received_last_modified=getattr(collector, "last_received_last_modified", None),
                        received_last_build_date=getattr(collector, "last_received_last_build_date", None),
                    )
                    return {
                        "source": source.name,
                        "run_id": run_id,
                        "status": "skipped_304",
                        "items_total": 0,
                        "items_new": 0,
                        "items_duplicate": 0,
                        "items_failed": 0,
                    }

                if getattr(collector, "last_was_same_build_date", False):
                    _finalize_run(
                        run_id=run_id,
                        source_id=source.id,
                        status="success",
                        items_total=0,
                        items_new=0,
                        items_duplicate=0,
                        items_failed=0,
                        http_status=getattr(collector, "last_http_status", None),
                        response_bytes=getattr(collector, "last_response_bytes", None),
                        sent_etag=getattr(collector, "last_sent_etag", None),
                        sent_if_modified_since=getattr(collector, "last_sent_if_modified_since", None),
                        received_etag=getattr(collector, "last_received_etag", None),
                        received_last_modified=getattr(collector, "last_received_last_modified", None),
                        received_last_build_date=getattr(collector, "last_received_last_build_date", None),
                    )
                    return {
                        "source": source.name,
                        "run_id": run_id,
                        "status": "success",
                        "items_total": 0,
                        "items_new": 0,
                        "items_duplicate": 0,
                        "items_failed": 0,
                    }

                item_errors = list(getattr(collector, "last_item_errors", []) or [])
                _log_item_errors(run_id, source.id, item_errors)

                inserted_ids, duplicates, db_failures = _persist_articles(run_id, source.id, articles)
                inserted = len(inserted_ids)
                parse_errors = int(getattr(collector, "last_parse_errors", 0))
                item_failures = int(getattr(collector, "last_item_failures", 0))
                total_failures = item_failures + db_failures
                enqueue_failed = False

                if inserted > 0 and _source_uses_html_enrichment(source):
                    try:
                        await _enqueue_html_enrichment(source, inserted)
                    except Exception as exc:
                        enqueue_failed = True
                        _log_run_error(
                            run_id,
                            source.id,
                            "unknown",
                            f"Failed to enqueue deferred enrichment: {exc}",
                            mark_run_failed=False,
                            increment_source_error=True,
                        )
                        log_event(
                            logger,
                            logging.WARNING,
                            "deferred_enrichment_enqueue_failed",
                            source_id=source.id,
                            source_name=source.name,
                            run_id=run_id,
                            items_new=inserted,
                            error_message=str(exc),
                        )

                status = "partial" if total_failures > 0 or enqueue_failed else "success"
                _finalize_run(
                    run_id=run_id,
                    source_id=source.id,
                    status=status,
                    items_total=getattr(collector, "last_items_total", len(articles)),
                    items_new=inserted,
                    items_duplicate=duplicates,
                    items_failed=total_failures,
                    http_status=getattr(collector, "last_http_status", None),
                    response_bytes=getattr(collector, "last_response_bytes", None),
                    parse_errors_count=parse_errors + max(0, item_failures - parse_errors),
                    sent_etag=getattr(collector, "last_sent_etag", None),
                    sent_if_modified_since=getattr(collector, "last_sent_if_modified_since", None),
                    received_etag=getattr(collector, "last_received_etag", None),
                    received_last_modified=getattr(collector, "last_received_last_modified", None),
                    received_last_build_date=getattr(collector, "last_received_last_build_date", None),
                )
                return {
                    "source": source.name,
                    "run_id": run_id,
                    "status": status,
                    "items_total": getattr(collector, "last_items_total", len(articles)),
                    "items_new": inserted,
                    "items_duplicate": duplicates,
                    "items_failed": total_failures,
                }
            except asyncio.TimeoutError:
                _log_run_error(run_id, source.id, "network", f"Source budget exceeded: {SOURCE_BUDGET_SECONDS}s")
                _finalize_run(
                    run_id=run_id,
                    source_id=source.id,
                    status="timeout",
                    items_total=0,
                    items_new=0,
                    items_duplicate=0,
                    items_failed=1,
                    http_status=None,
                    response_bytes=None,
                    http_errors_count=1,
                )
                raise
            except Exception as exc:
                error_type, http_status = _classify_source_exception(exc)
                _log_run_error(run_id, source.id, error_type, str(exc), http_status=http_status)
                _finalize_run(
                    run_id=run_id,
                    source_id=source.id,
                    status="failed",
                    items_total=0,
                    items_new=0,
                    items_duplicate=0,
                    items_failed=1,
                    http_status=http_status,
                    response_bytes=None,
                    http_errors_count=1 if error_type in {"network", "http_4xx", "http_5xx", "http_429"} else 0,
                    parse_errors_count=1 if error_type == "rss_parse" else 0,
                )
                raise
    finally:
        await clear_collection_pending(source.id)


def run_collect_source(source_name: str) -> dict:
    """Sync wrapper for CLI usage."""
    return asyncio.run(collect_source_once(source_name))
