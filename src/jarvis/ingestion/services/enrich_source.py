"""HTML enrichment path for already discovered RSS articles."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from jarvis.db.models import IngestionError, IngestionRun, News, NewsRaw, Source
from jarvis.db.models.ingestion_run import ENRICHMENT_RUN_KIND
from jarvis.db.session import SyncSessionLocal
from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings
from jarvis.ingestion.extraction.postprocess import apply_postprocess_rules, apply_pre_extraction_rules
from jarvis.ingestion.extraction.source_specific import extract_source_specific
from jarvis.ingestion.extraction.trafilatura_extractor import extract_with_precision, extract_with_recall
from jarvis.ingestion.services.distributed_lock import (
    acquire_enrichment_lock,
    clear_enrichment_pending,
    consume_enrichment_rerun,
    mark_enrichment_pending,
)
from jarvis.ingestion.services.health import refresh_source_health


DEFAULT_USER_AGENT = "JarvisLayer1/0.1 (+research project; contact: local-dev)"
logger = logging.getLogger(__name__)


def _load_source_by_name(name: str) -> Source | None:
    with SyncSessionLocal() as session:
        return session.scalar(select(Source).where(Source.name == name))


def _load_pending_articles(source_id: int, limit: int) -> list[News]:
    with SyncSessionLocal() as session:
        stmt = (
            select(News)
            .where(
                News.source_id == source_id,
                News.content.is_(None),
                News.content_status.in_(["partial", "extraction_failed"]),
            )
            .order_by(News.published_at.desc().nullslast(), News.id.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


def _source_uses_html_enrichment(source: Source) -> bool:
    method = str((source.config or {}).get("full_text_method") or "")
    return method.startswith("html_")


def _normalize_title_like_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = " ".join(value.split()).strip().lower()
    return normalized


def _strip_bfm_duplicated_title(content: str | None, title: str | None, source: Source) -> str | None:
    source_key = str((source.config or {}).get("source_key") or "").strip().lower()
    if source_key not in {"bfm", "cnews"} or not content or not title:
        return content

    lines = [line.strip() for line in content.splitlines()]
    non_empty = [line for line in lines if line]
    if not non_empty:
        return content

    first_line = non_empty[0]
    if _normalize_title_like_text(first_line) != _normalize_title_like_text(title):
        return content

    if source_key == "bfm":
        # BFM pages often repeat the title and then emit a separate one-line lead
        # before the body. For Layer 1 output we keep only the article body.
        remaining_lines = non_empty[2:] if len(non_empty) >= 2 else []
    else:
        remaining_lines = non_empty[1:]
    return "\n".join(remaining_lines).strip() or None


def _has_pending_articles(source_id: int) -> bool:
    with SyncSessionLocal() as session:
        stmt = (
            select(News.id)
            .where(
                News.source_id == source_id,
                News.content.is_(None),
                News.content_status.in_(["partial", "extraction_failed"]),
            )
            .limit(1)
        )
        return session.scalar(stmt) is not None


async def _schedule_followup_enrichment(source: Source, limit: int) -> bool:
    from jarvis.ingestion.tasks.enrichment_tasks import enrich_source_pending_task

    settings = get_settings()
    pending_ttl = max(settings.source_lock_ttl_seconds, settings.source_budget_seconds + 60)
    pending_marked = await mark_enrichment_pending(source.id, pending_ttl)
    if not pending_marked:
        return False

    try:
        enrich_source_pending_task.apply_async(args=[source.name, limit], queue="enrichment_queue")
    except Exception:
        await clear_enrichment_pending(source.id)
        raise

    return True


def _start_run(source_id: int, *, run_kind: str = ENRICHMENT_RUN_KIND) -> int:
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
    items_failed: int,
    extraction_errors_count: int,
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
        run.items_duplicate = 0
        run.items_failed = items_failed
        run.extraction_errors_count = extraction_errors_count
        run.finished_at = finished_at
        duration_seconds = (finished_at - run.started_at).total_seconds()
        run.duration_seconds = duration_seconds

        source.last_run_id = run.id
        source_name = source.name
        if status in {"success", "partial"}:
            source.error_count = 0

        session.commit()

    refresh_source_health(source_id)
    log_event(
        logger,
        logging.INFO if status == "success" else logging.WARNING,
        "enrichment_run_completed",
        source_id=source_id,
        source_name=source_name,
        run_id=run_id,
        run_kind=ENRICHMENT_RUN_KIND,
        status=status,
        items_total=items_total,
        items_enriched=items_new,
        items_failed=items_failed,
        extraction_errors_count=extraction_errors_count,
        duration_seconds=duration_seconds,
    )


def _log_extraction_error(
    *,
    run_id: int,
    source_id: int,
    item_url: str,
    error_message: str,
    http_status: int | None = None,
) -> None:
    error_type = "extraction" if http_status is None else _map_http_error_type(http_status)
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
        source = session.get(Source, source_id)
        if source is not None:
            source.last_error = error_message
            source.error_count = (source.error_count or 0) + 1
        session.commit()
    log_event(
        logger,
        logging.WARNING,
        "extraction_failed",
        source_id=source_id,
        run_id=run_id,
        run_kind=ENRICHMENT_RUN_KIND,
        item_url=item_url,
        http_status=http_status,
        error_type=error_type,
        error_message=error_message,
    )


def _map_http_error_type(status_code: int) -> str:
    if status_code == 429:
        return "http_429"
    if 400 <= status_code < 500:
        return "http_4xx"
    if 500 <= status_code < 600:
        return "http_5xx"
    return "extraction"


def _persist_enrichment(
    *,
    news_id: int,
    content: str | None,
    content_status: str,
    extraction_method: str,
    parser_version: str,
    raw_content: str | None,
    raw_format: str = "html",
    extra_updates: dict | None = None,
) -> None:
    with SyncSessionLocal() as session:
        news = session.get(News, news_id)
        if news is None:
            return

        news.content = content
        news.content_status = content_status
        news.extraction_method = extraction_method
        news.parser_version = parser_version

        if extra_updates:
            merged_extra = dict(news.extra or {})
            merged_extra.update(extra_updates)
            news.extra = merged_extra

        if raw_content is not None:
            stmt = insert(NewsRaw).values(
                news_id=news_id,
                raw_content=raw_content,
                raw_format=raw_format,
                parser_version=parser_version,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["news_id"],
                set_={
                    "raw_content": raw_content,
                    "raw_format": raw_format,
                    "parser_version": parser_version,
                },
            )
            session.execute(stmt)

        session.commit()


async def _enrich_single_article(
    *,
    article: News,
    source: Source,
    http_client: httpx.AsyncClient,
    run_id: int,
) -> tuple[bool, bool]:
    """Return (success, failed)."""
    method = (source.config or {}).get("full_text_method", "html_trafilatura")
    postprocess_rules = list((source.config or {}).get("postprocess_rules") or [])
    parser_version = "htmlenricher-v1"

    try:
        response = await http_client.get(article.url, headers={"User-Agent": DEFAULT_USER_AGENT})
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        _persist_enrichment(
            news_id=article.id,
            content=None,
            content_status="extraction_failed",
            extraction_method="http_error",
            parser_version=parser_version,
            raw_content=None,
        )
        _log_extraction_error(
            run_id=run_id,
            source_id=source.id,
            item_url=article.url,
            error_message=str(exc),
        )
        return False, True

    if response.status_code != 200:
        _persist_enrichment(
            news_id=article.id,
            content=None,
            content_status="extraction_failed",
            extraction_method="http_error",
            parser_version=parser_version,
            raw_content=response.text if response.text else None,
            extra_updates={"final_url_after_redirect": str(response.url)},
        )
        _log_extraction_error(
            run_id=run_id,
            source_id=source.id,
            item_url=article.url,
            error_message=f"HTTP {response.status_code}",
            http_status=response.status_code,
        )
        return False, True

    raw_html = response.text
    prepared_html = apply_pre_extraction_rules(raw_html, postprocess_rules)

    content: str | None = None
    content_status = "extraction_failed"
    extraction_method = "failed_all_levels"
    extra_updates: dict = {"final_url_after_redirect": str(response.url)}

    source_specific = extract_source_specific(prepared_html, source)
    if source_specific:
        extra_updates.update(source_specific.get("extra") or {})
        source_specific_content = source_specific.get("content")
    else:
        source_specific_content = None

    if source_specific_content and len(source_specific_content) >= 200:
        content = source_specific_content
        content_status = "ok"
        extraction_method = "html_source_specific"

    if content is None:
        precision_text = extract_with_precision(prepared_html)
        if precision_text:
            content = precision_text
            content_status = "ok"
            extraction_method = "trafilatura_precision"
        else:
            recall_text = extract_with_recall(prepared_html)
            if recall_text:
                content = recall_text
                content_status = "ok"
                extraction_method = "trafilatura_recall"

    content, snippet_lead = apply_postprocess_rules(
        content=content,
        snippet_lead=article.snippet_lead,
        rules=postprocess_rules,
    )
    article_title = getattr(article, "title", None)
    content = _strip_bfm_duplicated_title(content, article_title, source)

    _persist_enrichment(
        news_id=article.id,
        content=content,
        content_status=content_status,
        extraction_method=extraction_method,
        parser_version=parser_version,
        raw_content=raw_html,
        extra_updates=extra_updates,
    )

    if snippet_lead != article.snippet_lead:
        with SyncSessionLocal() as session:
            news = session.get(News, article.id)
            if news is not None:
                news.snippet_lead = snippet_lead
                session.commit()

    if content is None:
        _log_extraction_error(
            run_id=run_id,
            source_id=source.id,
            item_url=article.url,
            error_message="Extraction failed on all levels",
        )
        return False, True

    return True, False


async def enrich_source_pending_once(source_name: str, limit: int = 10) -> dict:
    """Enrich pending HTML articles for a single source."""
    source = _load_source_by_name(source_name)
    if source is None:
        raise ValueError(f"Unknown source: {source_name}")

    lock_held = False
    followup_needed = False
    try:
        async with acquire_enrichment_lock(source.id) as lock_acquired:
            if not lock_acquired:
                log_event(
                    logger,
                    logging.DEBUG,
                    "enrichment_run_skipped_locked",
                    source_id=source.id,
                    source_name=source.name,
                )
                return {
                    "source": source.name,
                    "status": "skipped_locked",
                    "run_id": None,
                }
            lock_held = True

            pending_articles = _load_pending_articles(source.id, limit)
            run_id = _start_run(source.id)

            if not pending_articles:
                _finalize_run(
                    run_id=run_id,
                    source_id=source.id,
                    status="success",
                    items_total=0,
                    items_new=0,
                    items_failed=0,
                    extraction_errors_count=0,
                )
                return {
                    "source": source.name,
                    "run_id": run_id,
                    "items_total": 0,
                    "items_enriched": 0,
                    "items_failed": 0,
                }

            successes = 0
            failures = 0
            enriched_ids: list[int] = []

            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                for index, article in enumerate(pending_articles):
                    success, failed = await _enrich_single_article(
                        article=article,
                        source=source,
                        http_client=client,
                        run_id=run_id,
                    )
                    successes += int(success)
                    failures += int(failed)
                    if success:
                        enriched_ids.append(article.id)
                    if index < len(pending_articles) - 1 and source.crawl_delay > 0:
                        await asyncio.sleep(float(source.crawl_delay))

            status = "partial" if failures > 0 else "success"
            _finalize_run(
                run_id=run_id,
                source_id=source.id,
                status=status,
                items_total=len(pending_articles),
                items_new=successes,
                items_failed=failures,
                extraction_errors_count=failures,
            )
            followup_needed = await consume_enrichment_rerun(source.id) or _has_pending_articles(source.id)

            return {
                "source": source.name,
                "run_id": run_id,
                "items_total": len(pending_articles),
                "items_enriched": successes,
                "items_failed": failures,
                "enriched_news_ids": enriched_ids,
                "followup_needed": followup_needed,
            }
    finally:
        if lock_held:
            await clear_enrichment_pending(source.id)
            if followup_needed:
                scheduled = await _schedule_followup_enrichment(source, limit)
                log_event(
                    logger,
                    logging.INFO if scheduled else logging.WARNING,
                    "enrichment_followup_scheduled" if scheduled else "enrichment_followup_skipped",
                    source_id=source.id,
                    source_name=source.name,
                    followup_limit=limit,
                )


def run_enrich_source_pending(source_name: str, limit: int = 10) -> dict:
    """Sync wrapper for CLI usage."""
    return asyncio.run(enrich_source_pending_once(source_name=source_name, limit=limit))
