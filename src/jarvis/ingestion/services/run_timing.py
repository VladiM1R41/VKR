"""Time helpers for ingestion run bookkeeping."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return an aware UTC timestamp from the application process."""
    return datetime.now(timezone.utc)


def to_aware_utc(value: datetime | None) -> datetime | None:
    """Normalize DB/application datetimes before duration math."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_duration_seconds(started_at: datetime | None, finished_at: datetime) -> float | None:
    """Return a non-negative run duration.

    `started_at` may come from PostgreSQL `NOW()` on older rows while `finished_at`
    is app-time. Clamping avoids negative telemetry when clocks differ slightly.
    """
    started_at_utc = to_aware_utc(started_at)
    finished_at_utc = to_aware_utc(finished_at)
    if started_at_utc is None or finished_at_utc is None:
        return None
    return max(0.0, (finished_at_utc - started_at_utc).total_seconds())
