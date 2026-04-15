"""Date parsing helpers for RSS feeds."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_feed_datetime(raw_value: str | None) -> tuple[datetime | None, bool]:
    """Parse an RSS date string into UTC.

    Returns:
        tuple[datetime | None, bool]:
            - parsed UTC datetime or None
            - date_inferred flag (True when parsing failed)
    """
    if not raw_value:
        return None, True

    raw_value = raw_value.strip()
    if not raw_value:
        return None, True

    try:
        dt = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        return None, True

    if dt is None:
        return None, True

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc), False

