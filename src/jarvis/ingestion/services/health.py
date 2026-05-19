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
BACKPRESSURE_SKIPPED_RUN_STATUS = "skipped_backpressure"
NEUTRAL_PARSE_RUN_STATUSES = {BACKPRESSURE_SKIPPED_RUN_STATUS}
FEED_RUN_STATUSES = {"success", "partial"}
RECENT_RUNS_LIMIT = 10

logger = logging.getLogger(__name__)

SUCCESSFUL_EXTRACTION_STATUSES = ("ok", "partial")
TERMINAL_EXTRACTION_STATUSES = SUCCESSFUL_EXTRACTION_STATUSES + ("extraction_failed", "low", "paywall")
LOW_EXTRACTION_FLAGS = ("allow_extraction_70", "allow_low_extraction")

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

    # `items_duplicate` is treated as a feed/run observability metric here:
    # it reflects already-known duplicate items seen in the run, not only DB conflicts.
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


def _compute_consecutive_failures(statuses: list[str]) -> int:
    failures = 0
    for status in statuses:
        if status in SUCCESS_RUN_STATUSES:
            break
        if status in FAILED_RUN_STATUSES:
            failures += 1
    return failures


def _calculate_parse_success_rate(statuses: list[str]) -> float | None:
    attempted_statuses = [status for status in statuses if status not in NEUTRAL_PARSE_RUN_STATUSES]
    if not attempted_statuses:
        return None
    successful = sum(1 for status in attempted_statuses if status in SUCCESS_RUN_STATUSES)
    return successful / len(attempted_statuses)


def _summarize_run_window(runs: list[IngestionRun]) -> dict[str, float | int | None]:
    statuses = [str(run.status) for run in runs]
    return {
        "runs_count": len(runs),
        "attempted_runs_count": sum(1 for status in statuses if status not in NEUTRAL_PARSE_RUN_STATUSES),
        "parse_success_rate": _calculate_parse_success_rate(statuses),
        "consecutive_failures": _compute_consecutive_failures(statuses),
        "successful_streak": _compute_successful_streak(statuses),
        "http_errors_count": sum(int(run.http_errors_count or 0) for run in runs),
        "backpressure_skips_count": sum(1 for status in statuses if status == BACKPRESSURE_SKIPPED_RUN_STATUS),
    }


def _resolve_staleness_ratio_for_health(staleness_ratio: float | None, runs_24h: int) -> float | None:
    """Use staleness in status only when the source was actually fetched recently."""
    if runs_24h <= 0:
        return None
    return staleness_ratio


def _calculate_extraction_success_rate(*, successful_items: int, total_items: int) -> float | None:
    if total_items <= 0:
        return None
    return successful_items / total_items


def _load_recent_discovery_runs(session, source_id: int, limit: int = RECENT_RUNS_LIMIT) -> list[IngestionRun]:
    return list(
        session.scalars(
            select(IngestionRun)
            .where(
                IngestionRun.source_id == source_id,
                IngestionRun.run_kind == DISCOVERY_RUN_KIND,
            )
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
        )
    )


def _load_24h_run_diagnostics(session, source_id: int, since_dt: datetime) -> dict[str, float | int | None]:
    statuses = [
        str(status)
        for (status,) in session.execute(
            select(IngestionRun.status)
            .where(
                IngestionRun.source_id == source_id,
                IngestionRun.started_at >= since_dt,
                IngestionRun.run_kind == DISCOVERY_RUN_KIND,
            )
            .order_by(IngestionRun.started_at.desc())
        )
    ]
    http_errors_count = int(
        session.scalar(
            select(func.coalesce(func.sum(IngestionRun.http_errors_count), 0)).where(
                IngestionRun.source_id == source_id,
                IngestionRun.started_at >= since_dt,
                IngestionRun.run_kind == DISCOVERY_RUN_KIND,
            )
        )
        or 0
    )
    return {
        "runs_24h": len(statuses),
        "attempted_runs_24h": sum(1 for status in statuses if status not in NEUTRAL_PARSE_RUN_STATUSES),
        "parse_success_rate_24h": _calculate_parse_success_rate(statuses),
        "http_errors_count_24h": http_errors_count,
        "backpressure_skips_24h": sum(1 for status in statuses if status == BACKPRESSURE_SKIPPED_RUN_STATUS),
    }


def _load_extraction_success_rate(
    session,
    *,
    source_id: int,
    recent_run_ids: list[int] | None = None,
    since_dt: datetime | None = None,
) -> float | None:
    stmt = select(
        func.count(News.id)
        .filter(News.content_status.in_(TERMINAL_EXTRACTION_STATUSES))
        .label("attempted_items"),
        func.count()
        .filter(News.content_status.in_(SUCCESSFUL_EXTRACTION_STATUSES))
        .label("successful_items"),
    ).where(News.source_id == source_id)

    if recent_run_ids is not None:
        if not recent_run_ids:
            return None
        stmt = stmt.where(News.ingestion_run_id.in_(recent_run_ids))
    if since_dt is not None:
        stmt = stmt.where(News.ingested_at >= since_dt)

    items_stats = session.execute(stmt).one()
    total_items = int(items_stats.attempted_items or 0)
    successful_items = int(items_stats.successful_items or 0)
    return _calculate_extraction_success_rate(
        successful_items=successful_items,
        total_items=total_items,
    )


def _resolve_low_extraction_policy(source: Source) -> tuple[bool, float | None]:
    """Return a validated low-extraction policy from source config."""
    config = source.config or {}
    allow_low_extraction = any(bool(config.get(flag)) for flag in LOW_EXTRACTION_FLAGS)
    if not allow_low_extraction:
        return False, None

    raw_floor = config.get("extraction_floor")
    if raw_floor is None:
        log_event(
            logger,
            logging.WARNING,
            "low_extraction_policy_invalid",
            source_id=source.id,
            source_name=source.name,
            reason="missing_extraction_floor",
        )
        return False, None

    try:
        extraction_floor = float(raw_floor)
    except (TypeError, ValueError):
        log_event(
            logger,
            logging.WARNING,
            "low_extraction_policy_invalid",
            source_id=source.id,
            source_name=source.name,
            reason="invalid_extraction_floor",
            extraction_floor=raw_floor,
        )
        return False, None

    if not 0.0 <= extraction_floor <= 1.0:
        log_event(
            logger,
            logging.WARNING,
            "low_extraction_policy_invalid",
            source_id=source.id,
            source_name=source.name,
            reason="extraction_floor_out_of_range",
            extraction_floor=extraction_floor,
        )
        return False, None

    return True, extraction_floor


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
    backpressure_skips_count: int = 0,
    items_in_feed_deviation: float | None = None,
    duplicate_rate_deviation: float | None = None,
    allow_low_extraction: bool = False,
    extraction_floor: float | None = None,
) -> str:
    """Return source health based on the thresholds фиксированных в гайде."""

    parse_red_threshold = 0.70
    parse_yellow_threshold = 0.95
    extraction_red_threshold = extraction_floor if allow_low_extraction and extraction_floor is not None else 0.50
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
    if staleness_ratio is not None and staleness_ratio > 3:
        return "yellow"
    if http_errors_count_24h is not None and http_errors_count_24h > 5:
        return "yellow"
    if backpressure_skips_count > 0:
        return "yellow"
    if items_in_feed_deviation is not None and abs(items_in_feed_deviation) > 0.50:
        return "yellow"
    if duplicate_rate_deviation is not None and abs(duplicate_rate_deviation) > 0.30:
        return "yellow"

    return "green"


def _determine_health_reasons(
    *,
    consecutive_failures: int,
    parse_success_rate: float | None,
    extraction_success_rate: float | None,
    staleness_ratio: float | None = None,
    recent_http_4xx: bool = False,
    http_errors_count_24h: int | None = None,
    backpressure_skips_count: int = 0,
    items_in_feed_deviation: float | None = None,
    duplicate_rate_deviation: float | None = None,
    allow_low_extraction: bool = False,
    extraction_floor: float | None = None,
) -> list[str]:
    """Explain the health decision without changing the status thresholds."""

    reasons: list[str] = []
    parse_red_threshold = 0.70
    parse_yellow_threshold = 0.95
    extraction_red_threshold = extraction_floor if allow_low_extraction and extraction_floor is not None else 0.50
    extraction_yellow_threshold = 0.70 if allow_low_extraction else 0.90

    if recent_http_4xx:
        reasons.append("recent_http_4xx")
    if consecutive_failures >= 5:
        reasons.append("consecutive_failures_red")
    elif consecutive_failures >= 2:
        reasons.append("consecutive_failures_yellow")
    if parse_success_rate is not None and parse_success_rate < parse_red_threshold:
        reasons.append("parse_success_red")
    elif parse_success_rate is not None and parse_success_rate < parse_yellow_threshold:
        reasons.append("parse_success_yellow")
    if extraction_success_rate is not None and extraction_success_rate < extraction_red_threshold:
        reasons.append("extraction_success_red")
    elif extraction_success_rate is not None and extraction_success_rate < extraction_yellow_threshold:
        reasons.append("extraction_success_yellow")
    if staleness_ratio is not None and staleness_ratio > 10:
        reasons.append("staleness_red")
    elif staleness_ratio is not None and staleness_ratio > 3:
        reasons.append("staleness_yellow")
    if http_errors_count_24h is not None and http_errors_count_24h > 5:
        reasons.append("http_errors_yellow")
    if backpressure_skips_count > 0:
        reasons.append("backpressure_skips_yellow")
    if items_in_feed_deviation is not None and abs(items_in_feed_deviation) > 0.50:
        reasons.append("items_in_feed_deviation_yellow")
    if duplicate_rate_deviation is not None and abs(duplicate_rate_deviation) > 0.30:
        reasons.append("duplicate_rate_deviation_yellow")
    return reasons


def refresh_source_health(source_id: int, *, persist: bool = True) -> dict | None:
    """Recalculate source aggregates after each ingestion run."""

    since_dt = datetime.now(timezone.utc) - timedelta(hours=24)
    baseline_since_dt = datetime.now(timezone.utc) - timedelta(days=7)

    with SyncSessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            return

        old_health = source.health_status

        recent_runs = _load_recent_discovery_runs(session, source_id)
        recent_run_ids = [int(run.id) for run in recent_runs]
        run_window = _summarize_run_window(recent_runs)
        diagnostics_24h = _load_24h_run_diagnostics(session, source_id, since_dt)

        parse_success_rate = run_window["parse_success_rate"]
        consecutive_failures = int(run_window["consecutive_failures"] or 0)
        successful_streak = int(run_window["successful_streak"] or 0)
        http_errors_count_recent = int(run_window["http_errors_count"] or 0)
        backpressure_skips_recent = int(run_window["backpressure_skips_count"] or 0)

        extraction_success_rate = _load_extraction_success_rate(
            session,
            source_id=source_id,
            recent_run_ids=recent_run_ids,
        )
        extraction_success_rate_24h = _load_extraction_success_rate(
            session,
            source_id=source_id,
            since_dt=since_dt,
        )

        latest_published_at = session.scalar(
            select(func.max(News.published_at)).where(News.source_id == source_id)
        )

        recent_http_4xx = False
        if recent_run_ids:
            recent_http_4xx = bool(
                session.scalar(
                    select(func.count())
                    .select_from(IngestionError)
                    .where(
                        IngestionError.source_id == source_id,
                        IngestionError.run_id.in_(recent_run_ids),
                        IngestionError.error_type == "http_4xx",
                        IngestionError.http_status.in_([401, 403]),
                    )
                )
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
        staleness_ratio_for_health = _resolve_staleness_ratio_for_health(
            staleness_ratio,
            int(diagnostics_24h["attempted_runs_24h"] or 0),
        )

        items_in_feed_deviation, duplicate_rate_deviation = _compute_feed_deviations(
            session,
            source_id,
            baseline_since_dt,
        )

        allow_low_extraction, extraction_floor = _resolve_low_extraction_policy(source)
        new_health = determine_health_status(
            consecutive_failures=consecutive_failures,
            parse_success_rate=parse_success_rate,
            extraction_success_rate=extraction_success_rate,
            staleness_ratio=staleness_ratio_for_health,
            recent_http_4xx=recent_http_4xx,
            http_errors_count_24h=http_errors_count_recent,
            backpressure_skips_count=backpressure_skips_recent,
            items_in_feed_deviation=items_in_feed_deviation,
            duplicate_rate_deviation=duplicate_rate_deviation,
            allow_low_extraction=allow_low_extraction,
            extraction_floor=extraction_floor,
        )
        health_reasons = _determine_health_reasons(
            consecutive_failures=consecutive_failures,
            parse_success_rate=parse_success_rate,
            extraction_success_rate=extraction_success_rate,
            staleness_ratio=staleness_ratio_for_health,
            recent_http_4xx=recent_http_4xx,
            http_errors_count_24h=http_errors_count_recent,
            backpressure_skips_count=backpressure_skips_recent,
            items_in_feed_deviation=items_in_feed_deviation,
            duplicate_rate_deviation=duplicate_rate_deviation,
            allow_low_extraction=allow_low_extraction,
            extraction_floor=extraction_floor,
        )

        snapshot = {
            "source_id": source.id,
            "source_name": source.name,
            "health_status": new_health,
            "health_reasons": health_reasons,
            "consecutive_failures": consecutive_failures,
            "parse_success_rate": parse_success_rate,
            "extraction_success_rate": extraction_success_rate,
            "parse_success_rate_24h": diagnostics_24h["parse_success_rate_24h"],
            "extraction_success_rate_24h": extraction_success_rate_24h,
            "runs_24h": diagnostics_24h["runs_24h"],
            "attempted_runs_24h": diagnostics_24h["attempted_runs_24h"],
            "http_errors_count_24h": diagnostics_24h["http_errors_count_24h"],
            "backpressure_skips_recent": backpressure_skips_recent,
            "backpressure_skips_24h": diagnostics_24h["backpressure_skips_24h"],
            "recent_runs_count": run_window["runs_count"],
            "recent_attempted_runs_count": run_window["attempted_runs_count"],
            "staleness_ratio": staleness_ratio,
            "staleness_ratio_used_for_health": staleness_ratio_for_health,
            "latest_published_at": latest_published_at,
            "avg_latency_minutes": float(avg_latency_minutes) if avg_latency_minutes is not None else None,
            "crawl_interval": source.crawl_interval,
        }

        if not persist:
            return snapshot

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
                health_reasons=health_reasons,
                crawl_interval=source.crawl_interval,
            )

        snapshot["crawl_interval"] = source.crawl_interval
        return snapshot
