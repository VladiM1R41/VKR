from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from jarvis.ingestion.collectors.rss import RSSCollector
from jarvis.ingestion.extraction.source_specific import extract_source_specific
from tests.conftest import build_source_stub, load_rss_items


def _build_rt_source():
    return SimpleNamespace(
        config={
            "source_key": "rt",
            "extraction_strategy": {
                "css_blocks": [".article__summary", ".article__text"],
                "tags_block": ".article__tags-trends",
            },
        }
    )


def test_rt_source_specific_extractor_collects_summary_text_and_tags() -> None:
    html = """
    <html><body>
      <div class="article__summary">
        <p>Краткий лид статьи с достаточной длиной для уверенного отбора в source-specific extractor.</p>
      </div>
      <div class="article__text">
        <p>Первый абзац основного текста с дополнительными деталями и контекстом, чтобы статья не выглядела обрезанной.</p>
        <figure>Картинка</figure>
        <p>Второй абзац основного текста продолжает тему и делает итоговый материал заметно длиннее порога в двести символов.</p>
      </div>
      <div class="article__tags-trends">
        <a href="/tags/1">Европа</a>
        <a href="/tags/2">Газ</a>
      </div>
    </body></html>
    """

    result = extract_source_specific(html, _build_rt_source())

    assert result is not None
    assert result["content"] == (
        "Краткий лид статьи с достаточной длиной для уверенного отбора в source-specific extractor.\n\n"
        "Первый абзац основного текста с дополнительными деталями и контекстом, чтобы статья не выглядела обрезанной.\n"
        "Второй абзац основного текста продолжает тему и делает итоговый материал заметно длиннее порога в двести символов."
    )
    assert result["extra"]["tags"] == ["Европа", "Газ"]


def test_rt_source_specific_extractor_returns_none_content_when_too_short() -> None:
    html = """
    <html><body>
      <div class="article__summary"><p>Слишком коротко.</p></div>
    </body></html>
    """

    result = extract_source_specific(html, _build_rt_source())

    assert result is not None
    assert result["content"] is None


def test_rt_source_specific_extractor_collects_all_matching_blocks_per_selector() -> None:
    html = """
    <html><body>
      <div class="article__summary"><p>Первый лидовый блок с достаточной длиной для итогового текста.</p></div>
      <div class="article__summary"><p>Второй лидовый блок не должен потеряться.</p></div>
      <div class="article__text"><p>Первый основной абзац статьи с деталями и контекстом.</p></div>
      <div class="article__text"><p>Второй основной абзац статьи тоже должен войти в content.</p></div>
    </body></html>
    """

    result = extract_source_specific(html, _build_rt_source())

    assert result is not None
    assert result["content"] == (
        "Первый лидовый блок с достаточной длиной для итогового текста.\n\n"
        "Второй лидовый блок не должен потеряться.\n\n"
        "Первый основной абзац статьи с деталями и контекстом.\n\n"
        "Второй основной абзац статьи тоже должен войти в content."
    )


def test_rbc_fixture_no_link_jacking_and_description_unescaped() -> None:
    source = build_source_stub("rbc")
    collector = RSSCollector(source, http_client=None)
    items = load_rss_items("rbc")[:10]

    parsed = [collector._parse_item(item) for item in items]
    parsed = [article for article in parsed if article is not None]

    assert parsed, "RBC fixture should yield parseable articles"
    assert all(article.url.startswith("https://") for article in parsed)
    assert all("rbc.ru" in article.canonical_url for article in parsed)
    assert any("«" in (article.snippet_lead or "") for article in parsed)


def test_aif_fixture_preserves_story_tag_and_related_urls() -> None:
    source = build_source_stub("aif_news")
    collector = RSSCollector(source, http_client=None)

    parsed = []
    for item in load_rss_items("aif_news")[:50]:
        article = collector._parse_item(item)
        if article is not None:
            parsed.append(article)

    assert parsed, "AIF fixture should yield parseable articles"
    assert any("yandex_story_tag" in article.extra for article in parsed)
    assert any("source_related_urls" in article.extra for article in parsed)


def test_kommersant_main_fixture_keeps_raw_title_and_extracts_subtitle() -> None:
    source = build_source_stub("kommersant_main")
    collector = RSSCollector(source, http_client=None)

    for item in load_rss_items("kommersant_main"):
        title_tag = item.find("title", recursive=False)
        if title_tag and " // " in title_tag.get_text(strip=True):
            article = collector._parse_item(item)
            assert article is not None
            assert " // " in article.title
            assert article.extra.get("subtitle")
            return

    pytest.fail("Kommersant main fixture should contain a title with ' // ' subtitle separator")


def test_mk_fixture_stores_source_host_for_regional_items() -> None:
    source = build_source_stub("mk")
    collector = RSSCollector(source, http_client=None)

    for item in load_rss_items("mk"):
        link_tag = item.find("link", recursive=False)
        if not link_tag:
            continue
        link = link_tag.get_text(strip=True)
        if "://spb.mk.ru/" in link or "://ekb.mk.ru/" in link or "://kuban.mk.ru/" in link:
            article = collector._parse_item(item)
            assert article is not None
            assert article.extra.get("source_host")
            assert article.extra["source_host"] != "mk.ru"
            return

    pytest.skip("MK fixture does not contain a regional host item in the sampled window")


def test_ria_fixture_maps_rian_type_into_source_content_type() -> None:
    source = build_source_stub("ria")
    collector = RSSCollector(source, http_client=None)

    for item in load_rss_items("ria")[:20]:
        article = collector._parse_item(item)
        if article is None:
            continue
        if "source_content_type" in article.extra:
            assert article.content_type in {"news", "analysis", "press_release", "opinion"}
            return

    pytest.skip("RIA fixture sampled window did not expose rian:type")
