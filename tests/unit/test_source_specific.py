from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from jarvis.ingestion.collectors.rss import RSSCollector
from jarvis.ingestion.extraction.source_specific import extract_source_specific
from jarvis.ingestion.services.enrich_source import _source_specific_min_length
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


def test_rt_source_specific_keeps_inline_links_inside_sentences() -> None:
    html = """
    <html><body>
      <div class="article__summary">
        <p>Краткий лид статьи с достаточной длиной для уверенного отбора в source-specific extractor.</p>
      </div>
      <div class="article__text">
        <p>Первый абзац сообщает, что <a href="/world">важная ссылка внутри предложения</a> должна остаться на той же строке.</p>
        <p>Второй абзац основного текста продолжает тему и делает итоговый материал заметно длиннее порога в двести символов.</p>
      </div>
    </body></html>
    """

    result = extract_source_specific(html, _build_rt_source())

    assert result is not None
    assert result["content"] is not None
    assert "что важная ссылка внутри предложения должна" in result["content"]
    assert "\nважная ссылка внутри предложения\n" not in result["content"]


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


def test_bfm_source_specific_removes_inline_readalso_without_losing_paragraph_tail() -> None:
    html = """
    <html><body>
      <section class="inner-news article-news">
        <div class="current-article js-mediator-article">
          <p class="about-article">Lead should be stored as metadata.</p>
          <p>First article paragraph with enough detail for a valid body.</p>
          <p>
            <span class="see_also">
              <span class="see_also__title">Read also:</span>
              <a class="see_also__link" href="/news/1">Related card title</a>
            </span>
            Important article paragraph after related card with enough detail to prove it is not lost.
          </p>
          <p>Final article paragraph with enough context to keep the source-specific body over threshold.</p>
        </div>
      </section>
    </body></html>
    """

    result = extract_source_specific(html, build_source_stub("bfm"))

    assert result is not None
    assert result["content"] == (
        "First article paragraph with enough detail for a valid body.\n\n"
        "Important article paragraph after related card with enough detail to prove it is not lost.\n\n"
        "Final article paragraph with enough context to keep the source-specific body over threshold."
    )
    assert result["extra"]["source_lead"] == "Lead should be stored as metadata."
    assert "Read also" not in result["content"]
    assert "Related card title" not in result["content"]


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


def test_ria_source_specific_preserves_quote_blocks_and_skips_related_cards() -> None:
    html = """
    <html><body>
      <div class="article__body">
        <div class="article__block" data-type="text">
          <div class="article__text">МОСКВА, 26 апр — РИА Новости. Первый абзац перед цитатой.</div>
        </div>
        <div class="article__block" data-type="quote">
          <div class="article__quote">
            <div class="article__quote-bg">«</div>
            <div class="article__quote-text">"Важная цитата", — написал он.</div>
          </div>
        </div>
        <div class="article__block" data-type="article">
          <a class="article__article-title">Связанная статья не должна попасть в текст</a>
        </div>
        <div class="article__block" data-type="banner">Реклама</div>
        <div class="article__block" data-type="text">
          <div class="article__text">Абзац после цитаты с продолжением новости.</div>
        </div>
      </div>
    </body></html>
    """

    result = extract_source_specific(html, build_source_stub("ria"))

    assert result is not None
    assert result["content"] == (
        "МОСКВА, 26 апр — РИА Новости. Первый абзац перед цитатой.\n\n"
        '"Важная цитата", — написал он.\n\n'
        "Абзац после цитаты с продолжением новости."
    )
    assert "Связанная статья" not in result["content"]
    assert "Реклама" not in result["content"]


def test_ria_source_specific_accepts_short_structured_article() -> None:
    html = """
    <html><body>
      <div class="article__body">
        <div class="article__block" data-type="text">
          <div class="article__text">Короткий, но валидный первый абзац новости РИА.</div>
        </div>
        <div class="article__block" data-type="text">
          <div class="article__text">Второй абзац с полезной информацией и важной деталью для контекста.</div>
        </div>
      </div>
    </body></html>
    """

    result = extract_source_specific(html, build_source_stub("ria"))

    assert result is not None
    assert result["content"] is not None
    assert 100 <= len(result["content"]) < 200


def test_ria_source_specific_min_length_is_lower_than_default() -> None:
    assert _source_specific_min_length(build_source_stub("ria")) == 100
    assert _source_specific_min_length(build_source_stub("rt")) == 200
