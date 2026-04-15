from __future__ import annotations

import pytest

from jarvis.ingestion.collectors.rss import RSSCollector
from tests.conftest import RSS_SOURCE_KEYS, build_source_stub, fixture_path_for, load_rss_items


@pytest.mark.parametrize("source_key", RSS_SOURCE_KEYS)
def test_rss_fixture_exists_for_every_source(source_key: str) -> None:
    assert fixture_path_for(source_key).exists()


@pytest.mark.parametrize("source_key", RSS_SOURCE_KEYS)
def test_rss_fixture_contains_items(source_key: str) -> None:
    items = load_rss_items(source_key)
    assert items, f"{source_key} fixture must contain at least one <item>"


@pytest.mark.parametrize("source_key", RSS_SOURCE_KEYS)
def test_rss_collector_parses_first_items_from_fixture(source_key: str) -> None:
    source = build_source_stub(source_key)
    collector = RSSCollector(source, http_client=None)
    items = load_rss_items(source_key)[:5]

    parsed = [collector._parse_item(item) for item in items]
    parsed = [article for article in parsed if article is not None]

    assert parsed, f"{source_key} first fixture items should be parseable"
    assert all(article.title for article in parsed)
    assert all(article.canonical_url for article in parsed)
    assert all(article.channel_type == "RSS" for article in parsed)


@pytest.mark.parametrize("source_key", RSS_SOURCE_KEYS)
def test_rss_fixture_parsed_articles_have_consistent_contract(source_key: str) -> None:
    source = build_source_stub(source_key)
    collector = RSSCollector(source, http_client=None)
    items = load_rss_items(source_key)[:5]

    parsed = [collector._parse_item(item) for item in items]
    parsed = [article for article in parsed if article is not None]

    assert parsed, f"{source_key} should yield at least one NormalizedArticle"
    assert all(article.source_id == source.id for article in parsed)
    assert all(article.parser_version for article in parsed)
    assert all(article.title_hash for article in parsed)
    assert all(article.information_type in {"breaking", "daily", "analytics", "reference"} for article in parsed)
    assert all(article.content_type in {"news", "analysis", "press_release", "opinion"} for article in parsed)
