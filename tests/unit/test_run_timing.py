from datetime import datetime, timedelta, timezone

from jarvis.ingestion.services.run_timing import calculate_duration_seconds


def test_calculate_duration_seconds_clamps_negative_clock_skew() -> None:
    finished_at = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)
    started_at = finished_at + timedelta(seconds=2)

    assert calculate_duration_seconds(started_at, finished_at) == 0.0


def test_calculate_duration_seconds_normalizes_naive_started_at_as_utc() -> None:
    started_at = datetime(2026, 4, 23, 12, 0, 0)
    finished_at = datetime(2026, 4, 23, 12, 0, 3, tzinfo=timezone.utc)

    assert calculate_duration_seconds(started_at, finished_at) == 3.0
