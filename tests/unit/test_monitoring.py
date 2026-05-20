from types import SimpleNamespace

from jarvis.ingestion.services.health import expected_staleness_hours
from jarvis.ingestion.services.monitoring import (
    HEALTH_DASHBOARD_QUERY,
    _refresh_sources_for_report,
    summarize_date_audit_rows,
)


def _build_source(source_key: str, crawl_interval: int) -> SimpleNamespace:
    return SimpleNamespace(config={"source_key": source_key}, crawl_interval=crawl_interval)


def test_expected_staleness_hours_uses_explicit_source_override() -> None:
    source = _build_source("tass", 15)
    assert expected_staleness_hours(source) == 1.0


def test_expected_staleness_hours_falls_back_to_crawl_interval_ratio() -> None:
    source = _build_source("bfm", 30)
    assert expected_staleness_hours(source) == 2.0


def test_summarize_date_audit_rows_marks_future_items_as_high_severity() -> None:
    rows = [
        {
            "source": "Test source",
            "items_in_future": 2,
            "inferred_ratio": 0.0,
        }
    ]

    result = summarize_date_audit_rows(rows)

    assert result == [
        {
            "source": "Test source",
            "reason": "2 items in future",
            "severity": "high",
        }
    ]


def test_summarize_date_audit_rows_marks_inferred_ratio_as_medium_severity() -> None:
    rows = [
        {
            "source": "Test source",
            "items_in_future": 0,
            "inferred_ratio": 0.25,
        }
    ]

    result = summarize_date_audit_rows(rows)

    assert result == [
        {
            "source": "Test source",
            "reason": "inferred_ratio=25.0%",
            "severity": "medium",
        }
    ]


def test_refresh_sources_for_report_uses_non_persisting_refresh_in_dry_run(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []

    monkeypatch.setattr(
        "jarvis.ingestion.services.monitoring._list_active_source_ids",
        lambda: [11, 12],
    )

    def _fake_refresh(source_id: int, *, persist: bool = True):
        calls.append((source_id, persist))
        return {"source_id": source_id, "health_status": "green"}

    monkeypatch.setattr(
        "jarvis.ingestion.services.monitoring.refresh_source_health",
        _fake_refresh,
    )

    snapshots = _refresh_sources_for_report(dry_run=True)

    assert calls == [(11, False), (12, False)]
    assert snapshots == [
        {"source_id": 11, "health_status": "green"},
        {"source_id": 12, "health_status": "green"},
    ]


def test_refresh_sources_for_report_persists_when_not_dry_run(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []

    monkeypatch.setattr(
        "jarvis.ingestion.services.monitoring._list_active_source_ids",
        lambda: [21],
    )

    def _fake_refresh(source_id: int, *, persist: bool = True):
        calls.append((source_id, persist))
        return {"source_id": source_id, "health_status": "yellow"}

    monkeypatch.setattr(
        "jarvis.ingestion.services.monitoring.refresh_source_health",
        _fake_refresh,
    )

    snapshots = _refresh_sources_for_report(dry_run=False)

    assert calls == [(21, True)]
    assert snapshots == []


def test_health_dashboard_reports_backpressure_skips_without_parse_penalty() -> None:
    query = str(HEALTH_DASHBOARD_QUERY)

    assert "backpressure_skips_24h" in query
    assert "attempted_runs_24h" in query
    assert "status != 'skipped_backpressure'" in query
