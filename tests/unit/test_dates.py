from datetime import timezone

import pytest

from jarvis.ingestion.parsing.dates import parse_feed_datetime
from tests.conftest import RSS_SOURCE_KEYS, load_rss_items


def test_parse_feed_datetime_to_utc() -> None:
    dt, inferred = parse_feed_datetime("Tue, 07 Apr 2026 19:25:28 +0300")

    assert inferred is False
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.isoformat() == "2026-04-07T16:25:28+00:00"


def test_parse_feed_datetime_invalid() -> None:
    dt, inferred = parse_feed_datetime("not-a-date")

    assert dt is None
    assert inferred is True


def test_parse_feed_datetime_marks_naive_as_inferred() -> None:
    dt, inferred = parse_feed_datetime("Tue, 07 Apr 2026 19:25:28")

    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.isoformat() == "2026-04-07T19:25:28+00:00"
    assert inferred is True


@pytest.mark.parametrize("source_key", RSS_SOURCE_KEYS)
def test_parse_feed_datetime_works_on_fixture_dates(source_key: str) -> None:
    items = load_rss_items(source_key)[:5]
    raw_values: list[str] = []
    for item in items:
        for tag_name in ("pubDate", "published", "updated"):
            tag = item.find(tag_name, recursive=False)
            if tag and tag.get_text(strip=True):
                raw_values.append(tag.get_text(strip=True))
                break

    assert raw_values, f"{source_key} fixture should expose at least one RSS date field"
    parsed = [parse_feed_datetime(value) for value in raw_values]
    assert all(dt is not None for dt, _ in parsed)
    assert all(dt.tzinfo == timezone.utc for dt, _ in parsed if dt is not None)
