"""Health aggregation helpers for Layer 1 sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from statistics import median

from sqlalchemy import func, select

from jarvis.core.logging import log_event
from jarvis.db.models import IngestionError, IngestionRun, News, Source
from jarvis.db.models.ingestion_run import DISCOVERY_RUN_KIND
from jarvis.db.session import SyncSessionLocal


SUCCESS_RUN_STATUSES = {"success", "partial", "skipped_304"}
FAILED_RUN_STATUSES = {"failed", "timeout"}
FEED_RUN_STATUSES = {"success", "partial"}

logger = logging.getLogger(__name__)

STALENESS_HOURS_BY_SOURCE_KEY = {
    "tass": 1.0,
    "ria": 1.0,
    "lenta": 2.0,
    "ixbt": 12.0,
    "habr": 6.0,
    "kommersant_main": 24.0,
    "aif_articles": 24.0,
}


def get_source_key(source: Source) -> str | None:
    return str((source.config or {}).get("source_key") or "").strip() or None


def expected_staleness_hours(source: Source) -> float:
    source_key = get_source_key(source)
    if source_key and source_key in STALENESS_HOURS_BY_SOURCE_KEY:
        return STALENESS_HOURS_BY_SOURCE_KEY[source_key]

    return max(1.0, float(source.crawl_interval) / 15.0)


def calculate_relative_deviation(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline <= 0:
        return None
    return (current - baseline) / baseline


def _compute_feed_deviations(session, source_id: int, since_dt: datetime) -> tuple[float | None, float | None]:
    rows = list(
        session.execute(
            select(IngestionRun.items_total, IngestionRun.items_duplicate)
            .where(
                IngestionRun.source_id == source_id,
                IngestionRun.started_at >= since_dt,
                IngestionRun.run_kind == DISCOVERY_RUN_KIND,
                IngestionRun.status.in_(FEED_RUN_STATUSES),
                IngestionRun.items_total > 0,
            )
            .order_by(IngestionRun.started_at.desc())
            .limit(30)
        )
    )

    if len(rows) < 2:
        return None, None

    latest_total, latest_duplicate = rows[0]
    historical_rows = rows[1:]

    total_baseline_values = [float(total) for total, _ in historical_rows if total and total > 0]
    duplicate_rate_baseline_values = [
        float(duplicate or 0) / float(total)
        for total, duplicate in historical_rows
        if total and total > 0
    ]

    latest_duplicate_rate = (float(latest_duplicate or 0) / float(latest_total)) if latest_total else None

    items_in_feed_deviation = calculate_relative_deviation(
        float(latest_total) if latest_total else None,
        median(total_baseline_values) if total_baseline_values else None,
    )
    duplicate_rate_deviation = calculate_relative_deviation(
        latest_duplicate_rate,
        median(duplicate_rate_baseline_values) if duplicate_rate_baseline_values else None,
    )
    return items_in_feed_deviation, duplicate_rate_deviation


def _compute_successful_streak(statuses: list[str]) -> int:
    streak = 0
    for status in statuses:
        if status in SUCCESS_RUN_STATUSES:
            streak += 1
            continue
        break
    return streak


def _apply_health_interval_policy(source: Source, new_health: str, successful_streak: int) -> None:
    config = dict(source.config or {})
    base_crawl_interval = int(config.get("base_crawl_interval") or source.crawl_interval)
    config.setdefault("base_crawl_interval", base_crawl_interval)

    if new_health in {"yellow", "red"}:
        source.crawl_interval = max(source.crawl_interval, base_crawl_interval * 2)
    elif new_health == "green" and successful_streak >= 3:
        source.crawl_interval = base_crawl_interval

    source.config = config


def determine_health_status(
    *,
    consecutive_failures: int,
    parse_success_rate: float | None,
    extraction_success_rate: float | None,
    staleness_ratio: float | None = None,
    recent_http_4xx: bool = False,
    http_errors_count_24h: int | None = None,
    items_in_feed_deviation: float | None = None,
    duplicate_rate_deviation: float | None = None,
    allow_low_extraction: bool = False,
) -> str:
    """Return source health based on the thresholds фиксированных в гайде."""

    parse_red_threshold = 0.70
    parse_yellow_threshold = 0.95
    extraction_red_threshold = 0.50
    extraction_yellow_threshold = 0.70 if allow_low_extraction else 0.90

    if recent_http_4xx:
        return "red"
    if consecutive_failures >= 5:
        return "red"
    if parse_success_rate is not None and parse_success_rate < parse_red_threshold:
        return "red"
    if extraction_success_rate is not None and extraction_success_rate < extraction_red_threshold:
        return "red"
    if staleness_ratio is not None and staleness_ratio > 10:
        return "red"

    if consecutive_failures >= 2:
        return "yellow"
    if parse_success_rate is not None and parse_success_rate < parse_yellow_threshold:
        return "yellow"
    if extraction_success_rate is not None and extraction_success_rate < extraction_yellow_threshold:
        return "yellow"
    if staleness_ratio is not None and staleness_ratio > 4:
        return "yellow"
    if http_errors_count_24h is not None and http_errors_count_24h > 5:
        return "yellow"
    if items_in_feed_deviation is not None and abs(items_in_feed_deviation) > 0.50:
        return "yellow"
    if duplicate_rate_deviation is not None and abs(duplicate_rate_deviation) > 0.30:
        return "yellow"

    return "green"


def refresh_source_health(source_id: int) -> None:
    """Recalculate source aggregates after each ingestion run."""

    since_dt = datetime.now(timezone.utc) - timedelta(hours=24)
    baseline_since_dt = datetime.now(timezone.utc) - timedelta(days=7)

    with SyncSessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            return

        old_health = source.health_status

        runs = list(
            session.scalars(
                select(IngestionRun)
                .where(
                    IngestionRun.source_id == source_id,
                    IngestionRun.started_at >= since_dt,
                    IngestionRun.run_kind == DISCOVERY_RUN_KIND,
                )
                .order_by(IngestionRun.started_at.desc())
            )
        )

        parse_success_rate: float | None = None
        if runs:
            successful = sum(1 for run in runs if run.status in SUCCESS_RUN_STATUSES)
            parse_success_rate = successful / len(runs)

        consecutive_failures = 0
        status_history = [
            status
            for (status,) in session.execute(
                select(IngestionRun.status)
                .where(IngestionRun.source_id == source_id)
                .where(IngestionRun.run_kind == DISCOVERY_RUN_KIND)
                .order_by(IngestionRun.started_at.desc())
                .limit(20)
            )
        ]
        for status in status_history:
            if status in SUCCESS_RUN_STATUSES:
                break
            if status in FAILED_RUN_STATUSES:
                consecutive_failures += 1

        successful_streak = _compute_successful_streak(status_history)

        terminal_extraction_statuses = ("ok", "extraction_failed", "low", "paywall")
        items_stats = session.execute(
            select(
                func.count(News.id)
                .filter(News.content_status.in_(terminal_extraction_statuses))
                .label("attempted_items"),
                func.count()
                .filter(News.content_status == "ok")
                .label("ok_items"),
            ).where(
                News.source_id == source_id,
                News.ingested_at >= since_dt,
            )
        ).one()

        total_items = int(items_stats.attempted_items or 0)
        ok_items = int(items_stats.ok_items or 0)
        extraction_success_rate = (ok_items / total_items) if total_items > 0 else None

        latest_published_at = session.scalar(
            select(func.max(News.published_at)).where(
                News.source_id == source_id,
                News.ingested_at >= since_dt,
            )
        )

        recent_http_4xx = bool(
            session.scalar(
                select(func.count())
                .select_from(IngestionError)
                .where(
                    IngestionError.source_id == source_id,
                    IngestionError.occurred_at >= since_dt,
                    IngestionError.error_type == "http_4xx",
                    IngestionError.http_status.in_([401, 403]),
                )
            )
        )

        http_errors_count_24h = int(
            session.scalar(
                select(func.coalesce(func.sum(IngestionRun.http_errors_count), 0))
                .where(
                    IngestionRun.source_id == source_id,
                    IngestionRun.started_at >= since_dt,
                    IngestionRun.run_kind == DISCOVERY_RUN_KIND,
                )
            )
            or 0
        )

        avg_latency_minutes = session.scalar(
            select(
                func.avg(
                    func.extract("epoch", News.ingested_at - News.published_at) / 60.0
                )
            ).where(
                News.source_id == source_id,
                News.ingested_at >= since_dt,
                News.published_at.is_not(None),
            )
        )

        expected_staleness = expected_staleness_hours(source)
        staleness_ratio: float | None = None
        if latest_published_at is not None and expected_staleness > 0:
            staleness_hours = (datetime.now(timezone.utc) - latest_published_at).total_seconds() / 3600.0
            staleness_ratio = staleness_hours / expected_staleness

        items_in_feed_deviation, duplicate_rate_deviation = _compute_feed_deviations(
            session,
            source_id,
            baseline_since_dt,
        )

        new_health = determine_health_status(
            consecutive_failures=consecutive_failures,
            parse_success_rate=parse_success_rate,
            extraction_success_rate=extraction_success_rate,
            staleness_ratio=staleness_ratio,
            recent_http_4xx=recent_http_4xx,
            http_errors_count_24h=http_errors_count_24h,
            items_in_feed_deviation=items_in_feed_deviation,
            duplicate_rate_deviation=duplicate_rate_deviation,
            allow_low_extraction=bool((source.config or {}).get("allow_extraction_70")),
        )

        source.consecutive_failures = consecutive_failures
        source.parse_success_rate = parse_success_rate
        source.extraction_success_rate = extraction_success_rate
        source.health_status = new_health
        source.latest_published_at = latest_published_at
        source.avg_latency_minutes = float(avg_latency_minutes) if avg_latency_minutes is not None else None
        source.updated_at = datetime.now(timezone.utc)
        _apply_health_interval_policy(source, new_health, successful_streak)

        if consecutive_failures == 0:
            source.last_error = None
            source.error_count = 0

        session.commit()

        if old_health != new_health:
            log_event(
                logger,
                logging.WARNING if new_health in {"yellow", "red"} else logging.INFO,
                "health_transition",
                source_id=source.id,
                source_name=source.name,
                old_status=old_health,
                new_status=new_health,
                crawl_interval=source.crawl_interval,
            )
