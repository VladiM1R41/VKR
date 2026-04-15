from jarvis.ingestion.parsing.urls import canonicalize_url, normalized_title_hash


def test_canonicalize_url_removes_tracking_and_www() -> None:
    url = "https://www.Example.com/path/to/story/?utm_source=rss&id=42#fragment"
    result = canonicalize_url(url)

    assert result == "https://example.com/path/to/story?id=42"


def test_canonicalize_url_does_not_break_inner_www() -> None:
    url = "https://news.www.example.com/article"
    result = canonicalize_url(url)

    assert result == "https://news.www.example.com/article"


def test_normalized_title_hash_collapses_case_and_spaces() -> None:
    left = normalized_title_hash("  ЦБ   повысил   ставку ")
    right = normalized_title_hash("цб повысил ставку")

    assert left == right

