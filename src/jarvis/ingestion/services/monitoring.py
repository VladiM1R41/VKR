"""Monitoring, audit and daily health-report helpers for Layer 1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import delete, func, select, text

from jarvis.core.logging import log_event
from jarvis.db.models import IngestionError, IngestionRun, NewsRaw, Source
from jarvis.db.models.ingestion_run import DISCOVERY_RUN_KIND, ENRICHMENT_RUN_KIND
from jarvis.db.session import SyncSessionLocal
from jarvis.ingestion.services.health import refresh_source_health


logger = logging.getLogger(__name__)

DATE_AUDIT_QUERY = text(
    """
    SELECT
        s.name AS source,
        COUNT(*) AS items_count,
        MIN(n.published_at) AS oldest_published,
        MAX(n.published_at) AS newest_published,
        AVG(EXTRACT(EPOCH FROM (NOW() - n.published_at)) / 3600)::INT AS avg_hours_behind_now,
        COUNT(*) FILTER (WHERE n.published_at > NOW()) AS items_in_future,
        COUNT(*) FILTER (WHERE n.date_inferred = TRUE) AS items_with_inferred_date,
        ROUND(
            COUNT(*) FILTER (WHERE n.date_inferred = TRUE)::numeric / NULLIF(COUNT(*), 0),
            3
        ) AS inferred_ratio
    FROM news n
    JOIN sources s ON s.id = n.source_id
    WHERE n.ingested_at > NOW() - INTERVAL '24 hours'
    GROUP BY s.name
    ORDER BY items_in_future DESC, avg_hours_behind_now ASC
    """
)

HEALTH_DASHBOARD_QUERY = text(
    """
    SELECT
        s.id,
        s.name,
        s.health_status,
        s.consecutive_failures,
        ROUND(s.parse_success_rate::numeric, 3) AS parse_success,
        ROUND(s.extraction_success_rate::numeric, 3) AS extraction_success,
        (SELECT ROUND(
            (
                COUNT(*) FILTER (WHERE ir.status IN ('success','partial','skipped_304'))::numeric
                / NULLIF(COUNT(*) FILTER (WHERE ir.status != 'skipped_backpressure'), 0)
            ),
            3
         )
         FROM ingestion_runs ir
         WHERE ir.source_id = s.id
           AND ir.run_kind = 'discovery'
           AND ir.started_at > NOW() - INTERVAL '24 hours') AS parse_success_24h,
        (SELECT COUNT(*) FROM ingestion_runs ir
         WHERE ir.source_id = s.id
           AND ir.run_kind = 'discovery'
           AND ir.status = 'skipped_backpressure'
           AND ir.started_at > NOW() - INTERVAL '24 hours') AS backpressure_skips_24h,
        ROUND(s.avg_latency_minutes::numeric, 1) AS avg_latency_minutes,
        ROUND(s.source_utility::numeric, 3) AS source_utility,
        s.latest_published_at,
        EXTRACT(EPOCH FROM (NOW() - s.latest_published_at)) / 3600 AS staleness_hours,
        (SELECT COUNT(*) FROM ingestion_runs ir
         WHERE ir.source_id = s.id
           AND ir.run_kind = 'discovery'
           AND ir.started_at > NOW() - INTERVAL '24 hours') AS runs_24h,
        (SELECT COUNT(*) FROM ingestion_runs ir
         WHERE ir.source_id = s.id
           AND ir.run_kind = 'discovery'
           AND ir.status != 'skipped_backpressure'
           AND ir.started_at > NOW() - INTERVAL '24 hours') AS attempted_runs_24h,
        (SELECT COALESCE(SUM(items_new), 0) FROM ingestion_runs ir
         WHERE ir.source_id = s.id
           AND ir.run_kind = 'discovery'
           AND ir.started_at > NOW() - INTERVAL '24 hours') AS items_new_24h,
        (SELECT MAX(items_total) FROM ingestion_runs ir
         WHERE ir.source_id = s.id
           AND ir.run_kind = 'discovery'
           AND ir.started_at > NOW() - INTERVAL '24 hours'
           AND ir.status IN ('success', 'partial')) AS items_in_last_feed
    FROM sources s
    WHERE s.is_active = TRUE
    ORDER BY
        CASE s.health_status WHEN 'red' THEN 1 WHEN 'yellow' THEN 2 ELSE 3 END,
        s.name
    """
)

SOURCE_UTILITY_UPDATE = text(
    """
    WITH source_stats AS (
        SELECT
            n.source_id,
            COUNT(*) AS total_articles,
            COUNT(*) FILTER (
                WHERE n.event_cluster_id NOT IN (
                    SELECT DISTINCT n2.event_cluster_id
                    FROM news n2
                    WHERE n2.source_id != n.source_id
                      AND n2.event_cluster_id = n.event_cluster_id
                )
            ) AS unique_articles
        FROM news n
        WHERE n.ingested_at > NOW() - INTERVAL '30 days'
        GROUP BY n.source_id
    )
    UPDATE sources s
    SET source_utility = (ss.unique_articles::float / NULLIF(ss.total_articles, 0))
    FROM source_stats ss
    WHERE s.id = ss.source_id
    """
)


def summarize_date_audit_rows(rows: list[dict]) -> list[dict]:
    suspicious_sources: list[dict] = []
    for row in rows:
        items_in_future = int(row.get("items_in_future") or 0)
        inferred_ratio = float(row.get("inferred_ratio") or 0.0)

        if items_in_future > 0:
            suspicious_sources.append(
                {
                    "source": row["source"],
                    "reason": f"{items_in_future} items in future",
                    "severity": "high",
                }
            )
        elif inferred_ratio > 0.10:
            suspicious_sources.append(
                {
                    "source": row["source"],
                    "reason": f"inferred_ratio={inferred_ratio:.1%}",
                    "severity": "medium",
                }
            )
    return suspicious_sources


def run_date_audit() -> dict:
    with SyncSessionLocal() as session:
        rows = [dict(row) for row in session.execute(DATE_AUDIT_QUERY).mappings().all()]

    suspicious_sources = summarize_date_audit_rows(rows)

    if suspicious_sources:
        log_event(
            logger,
            logging.WARNING,
            "audit_dates_anomalies",
            anomalies_count=len(suspicious_sources),
            suspicious_sources=suspicious_sources,
        )
    else:
        log_event(
            logger,
            logging.INFO,
            "audit_dates_clean",
            total_sources=len(rows),
        )

    return {
        "rows": rows,
        "suspicious_sources": suspicious_sources,
        "anomalies_count": len(suspicious_sources),
        "total_sources": len(rows),
    }


def build_health_dashboard() -> list[dict]:
    with SyncSessionLocal() as session:
        rows = [dict(row) for row in session.execute(HEALTH_DASHBOARD_QUERY).mappings().all()]
    return rows


def _list_active_source_ids() -> list[int]:
    with SyncSessionLocal() as session:
        return list(
            session.scalars(
                select(Source.id)
                .where(Source.is_active.is_(True))
                .order_by(Source.id)
            ).all()
        )


def _refresh_sources_for_report(*, dry_run: bool) -> list[dict]:
    source_ids = _list_active_source_ids()
    snapshots: list[dict] = []
    for source_id in source_ids:
        snapshot = refresh_source_health(source_id, persist=not dry_run)
        if dry_run and snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def run_daily_health_check(*, dry_run: bool = False) -> dict:
    now_utc = datetime.now(timezone.utc)
    since_dt = now_utc - timedelta(hours=24)
    dry_run_snapshots = _refresh_sources_for_report(dry_run=dry_run)

    with SyncSessionLocal() as session:
        source_utility_updated = 0
        if not dry_run:
            source_utility_updated = int(session.execute(SOURCE_UTILITY_UPDATE).rowcount or 0)
            session.commit()

        audit_result = run_date_audit()
        dashboard_rows = build_health_dashboard() if not dry_run else dry_run_snapshots

        orphan_news_raw = int(
            session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM news_raw nr
                    LEFT JOIN news n ON n.id = nr.news_id
                    WHERE n.id IS NULL
                    """
                )
            ).scalar_one()
        )
        orphan_news_sources = int(
            session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM news n
                    LEFT JOIN sources s ON s.id = n.source_id
                    WHERE s.id IS NULL
                    """
                )
            ).scalar_one()
        )
        orphan_news_runs = int(
            session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM news n
                    LEFT JOIN ingestion_runs ir ON ir.id = n.ingestion_run_id
                    WHERE ir.id IS NULL
                    """
                )
            ).scalar_one()
        )

        articles_added_24h = int(
            session.scalar(
                select(func.coalesce(func.sum(IngestionRun.items_new), 0)).where(
                    IngestionRun.started_at >= since_dt,
                    IngestionRun.run_kind == DISCOVERY_RUN_KIND,
                )
            )
            or 0
        )
        articles_failed_24h = int(
            session.scalar(
                select(func.coalesce(func.sum(IngestionRun.items_failed), 0)).where(
                    IngestionRun.started_at >= since_dt,
                    IngestionRun.run_kind == DISCOVERY_RUN_KIND,
                )
            )
            or 0
        )
        extraction_failed_24h = int(
            session.scalar(
                select(func.coalesce(func.sum(IngestionRun.extraction_errors_count), 0)).where(
                    IngestionRun.started_at >= since_dt,
                    IngestionRun.run_kind == ENRICHMENT_RUN_KIND,
                )
            )
            or 0
        )

        cleanup_raw_query = select(func.count()).select_from(NewsRaw).where(
            NewsRaw.collected_at < now_utc - timedelta(days=90)
        )
        cleanup_errors_query = select(func.count()).select_from(IngestionError).where(
            IngestionError.occurred_at < now_utc - timedelta(days=30)
        )

        cleanup_raw_count = int(session.scalar(cleanup_raw_query) or 0)
        cleanup_errors_count = int(session.scalar(cleanup_errors_query) or 0)

        if not dry_run:
            session.execute(
                delete(NewsRaw).where(
                    NewsRaw.collected_at < now_utc - timedelta(days=90)
                )
            )
            session.execute(
                delete(IngestionError).where(
                    IngestionError.occurred_at < now_utc - timedelta(days=30)
                )
            )
            session.commit()

    report = {
        "date": str(now_utc.date()),
        "sources_total": len(dashboard_rows),
        "sources_green": sum(1 for row in dashboard_rows if row["health_status"] == "green"),
        "sources_yellow": sum(1 for row in dashboard_rows if row["health_status"] == "yellow"),
        "sources_red": sum(1 for row in dashboard_rows if row["health_status"] == "red"),
        "articles_added_24h": articles_added_24h,
        "articles_failed_24h": articles_failed_24h,
        "extraction_failed_rate": (
            extraction_failed_24h / articles_added_24h if articles_added_24h > 0 else None
        ),
        "audit_anomalies": int(audit_result["anomalies_count"]),
        "orphan_news_raw": orphan_news_raw,
        "orphan_news_sources": orphan_news_sources,
        "orphan_news_runs": orphan_news_runs,
        "cleanup_news_raw_deleted": 0 if dry_run else cleanup_raw_count,
        "cleanup_ingestion_errors_deleted": 0 if dry_run else cleanup_errors_count,
        "cleanup_news_raw_candidates": cleanup_raw_count,
        "cleanup_ingestion_errors_candidates": cleanup_errors_count,
        "source_utility_recomputed": source_utility_updated,
        "dry_run": dry_run,
    }

    log_event(logger, logging.INFO, "daily_health_check_report", **report)
    return report
