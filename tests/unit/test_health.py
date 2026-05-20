from types import SimpleNamespace

from jarvis.ingestion.services import health
from jarvis.ingestion.services.health import (
    _calculate_extraction_success_rate,
    _determine_health_reasons,
    _resolve_low_extraction_policy,
    _resolve_staleness_ratio_for_health,
    _summarize_run_window,
    determine_health_status,
)


def test_determine_health_status_green_when_metrics_are_healthy() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
        )
        == "green"
    )


def test_determine_health_status_yellow_on_degraded_parse_rate() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=0.90,
            extraction_success_rate=0.95,
        )
        == "yellow"
    )


def test_determine_health_status_red_on_recent_http_4xx() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            recent_http_4xx=True,
        )
        == "red"
    )


def test_determine_health_status_yellow_on_many_http_errors() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            http_errors_count_24h=6,
        )
        == "yellow"
    )


def test_determine_health_status_uses_lower_threshold_for_paywall_sources() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.75,
            allow_low_extraction=True,
        )
        == "green"
    )


def test_determine_health_status_yellow_on_duplicate_rate_deviation() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            duplicate_rate_deviation=0.31,
        )
        == "yellow"
    )


def test_determine_health_status_yellow_when_staleness_exceeds_three_x() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            staleness_ratio=3.1,
        )
        == "yellow"
    )


def test_determine_health_status_keeps_green_when_extraction_not_measured_yet() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=None,
        )
        == "green"
    )


def test_calculate_extraction_success_rate_counts_partial_as_success() -> None:
    assert _calculate_extraction_success_rate(successful_items=8, total_items=10) == 0.8
    assert _calculate_extraction_success_rate(successful_items=0, total_items=0) is None


def test_low_extraction_policy_requires_valid_floor(monkeypatch) -> None:
    events: list[tuple[str, dict]] = []
    source = SimpleNamespace(
        id=42,
        name="Paywall-like source",
        config={"allow_extraction_70": True},
    )
    monkeypatch.setattr(
        health,
        "log_event",
        lambda logger, level, event, **kwargs: events.append((event, kwargs)),
    )

    allow_low_extraction, extraction_floor = _resolve_low_extraction_policy(source)

    assert allow_low_extraction is False
    assert extraction_floor is None
    assert events[0][0] == "low_extraction_policy_invalid"
    assert events[0][1]["reason"] == "missing_extraction_floor"


def test_low_extraction_policy_returns_valid_floor() -> None:
    source = SimpleNamespace(
        id=43,
        name="Paywall-like source",
        config={"allow_extraction_70": True, "extraction_floor": 0.62},
    )

    assert _resolve_low_extraction_policy(source) == (True, 0.62)


def test_determine_health_status_uses_configured_extraction_floor_for_low_policy() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.61,
            allow_low_extraction=True,
            extraction_floor=0.62,
        )
        == "red"
    )


def test_summarize_run_window_uses_recent_run_statuses() -> None:
    runs = [
        SimpleNamespace(status="failed", http_errors_count=1),
        SimpleNamespace(status="timeout", http_errors_count=2),
        SimpleNamespace(status="success", http_errors_count=0),
        SimpleNamespace(status="failed", http_errors_count=5),
    ]

    summary = _summarize_run_window(runs)

    assert summary["runs_count"] == 4
    assert summary["attempted_runs_count"] == 4
    assert summary["parse_success_rate"] == 0.25
    assert summary["consecutive_failures"] == 2
    assert summary["successful_streak"] == 0
    assert summary["http_errors_count"] == 8
    assert summary["backpressure_skips_count"] == 0


def test_summarize_run_window_treats_backpressure_skips_as_parse_neutral() -> None:
    runs = [
        SimpleNamespace(status="skipped_backpressure", http_errors_count=0),
        SimpleNamespace(status="success", http_errors_count=0),
        SimpleNamespace(status="skipped_backpressure", http_errors_count=0),
    ]

    summary = _summarize_run_window(runs)

    assert summary["runs_count"] == 3
    assert summary["attempted_runs_count"] == 1
    assert summary["parse_success_rate"] == 1.0
    assert summary["consecutive_failures"] == 0
    assert summary["backpressure_skips_count"] == 2


def test_summarize_run_window_returns_no_parse_rate_for_only_backpressure_skips() -> None:
    runs = [
        SimpleNamespace(status="skipped_backpressure", http_errors_count=0),
        SimpleNamespace(status="skipped_backpressure", http_errors_count=0),
    ]

    summary = _summarize_run_window(runs)

    assert summary["attempted_runs_count"] == 0
    assert summary["parse_success_rate"] is None
    assert summary["backpressure_skips_count"] == 2


def test_backpressure_skips_degrade_health_without_parse_failure() -> None:
    assert (
        determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=0.95,
            backpressure_skips_count=1,
        )
        == "yellow"
    )
    assert _determine_health_reasons(
        consecutive_failures=0,
        parse_success_rate=1.0,
        extraction_success_rate=0.95,
        backpressure_skips_count=1,
    ) == ["backpressure_skips_yellow"]


def test_staleness_affects_health_only_after_recent_checks() -> None:
    assert _resolve_staleness_ratio_for_health(12.0, runs_24h=0) is None
    assert _resolve_staleness_ratio_for_health(12.0, runs_24h=1) == 12.0
