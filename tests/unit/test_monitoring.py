from types import SimpleNamespace

from jarvis.ingestion.services.health import expected_staleness_hours
from jarvis.ingestion.services.monitoring import summarize_date_audit_rows


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
            "source": "Тестовый источник",
            "items_in_future": 2,
            "inferred_ratio": 0.0,
        }
    ]

    result = summarize_date_audit_rows(rows)

    assert result == [
        {
            "source": "Тестовый источник",
            "reason": "2 items in future",
            "severity": "high",
        }
    ]


def test_summarize_date_audit_rows_marks_inferred_ratio_as_medium_severity() -> None:
    rows = [
        {
            "source": "Тестовый источник",
            "items_in_future": 0,
            "inferred_ratio": 0.25,
        }
    ]

    result = summarize_date_audit_rows(rows)

    assert result == [
        {
            "source": "Тестовый источник",
            "reason": "inferred_ratio=25.0%",
            "severity": "medium",
        }
    ]
