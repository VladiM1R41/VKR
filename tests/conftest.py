"""Shared pytest configuration for Layer 1 tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup, Tag

from jarvis.ingestion.bootstrap.source_seed_data import SOURCE_SEED_DATA


TESTS_DIR = Path(__file__).resolve().parent
RSS_FIXTURES_DIR = TESTS_DIR / "fixtures" / "rss"
HTML_FIXTURES_DIR = TESTS_DIR / "fixtures" / "html"

RSS_SOURCE_ROWS = [row for row in SOURCE_SEED_DATA if row["type"] == "rss"]
RSS_SOURCE_KEYS = [row["config"]["source_key"] for row in RSS_SOURCE_ROWS]
RSS_SOURCE_BY_KEY = {row["config"]["source_key"]: row for row in RSS_SOURCE_ROWS}


def fixture_path_for(source_key: str) -> Path:
    return RSS_FIXTURES_DIR / f"{source_key}_sample.xml"


def load_rss_fixture(source_key: str) -> bytes:
    path = fixture_path_for(source_key)
    return path.read_bytes()


def load_rss_soup(source_key: str) -> BeautifulSoup:
    return BeautifulSoup(load_rss_fixture(source_key), "xml")


def load_rss_items(source_key: str) -> list[Tag]:
    soup = load_rss_soup(source_key)
    channel = soup.find("channel")
    if channel:
        return channel.find_all("item", recursive=False)
    return soup.find_all("item", recursive=False)


def build_source_stub(source_key: str) -> SimpleNamespace:
    row = RSS_SOURCE_BY_KEY[source_key]
    return SimpleNamespace(
        id=row.get("id", 1),
        name=row["name"],
        url=row["url"],
        config=dict(row["config"]),
        default_info_type=row["default_info_type"],
        default_content_type=row["default_content_type"],
        crawl_delay=row["crawl_delay"],
    )
