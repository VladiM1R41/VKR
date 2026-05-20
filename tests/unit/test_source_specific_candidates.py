from types import SimpleNamespace

from bs4 import BeautifulSoup

from jarvis.ingestion.extraction.source_specific import extract_source_specific
from jarvis.ingestion.extraction.source_specific_candidates import (
    candidate_noise_markers,
    extract_aif_turbo_candidate,
    extract_candidate,
)


def _ria_source() -> SimpleNamespace:
    return SimpleNamespace(
        config={
            "source_key": "ria",
            "extraction_strategy": {
                "body_selector": ".article__body",
                "text_block_selector": ".article__block[data-type='text'] .article__text",
            },
        }
    )


def _aif_articles_source() -> SimpleNamespace:
    return SimpleNamespace(
        config={
            "source_key": "aif_articles",
            "full_text_method": "rss_turbo_structured",
            "full_text_tag": "turbo:content",
            "fallback_full_text_tag": "yandex:full-text",
            "postprocess_rules": [],
        }
    )


def _bfm_source() -> SimpleNamespace:
    return SimpleNamespace(config={"source_key": "bfm"})


def _rss_item(turbo_html: str) -> BeautifulSoup:
    soup = BeautifulSoup(
        f"""
        <item>
          <title>Sample title</title>
          <link>https://aif.ru/sample</link>
          <turbo:content><![CDATA[{turbo_html}]]></turbo:content>
        </item>
        """,
        "xml",
    )
    return soup.find("item")


def test_aif_articles_candidate_keeps_high_quality_turbo() -> None:
    turbo_html = """
    <p>First meaningful paragraph with enough detail to pass the source-specific article quality gate. It repeats useful context to make the article body long enough for the stricter articles threshold.</p>
    <p>Second meaningful paragraph with enough context to prove that the turbo body is complete. It repeats useful context to make the article body long enough for the stricter articles threshold.</p>
    <p>Third paragraph keeps the total article text comfortably above the configured minimum length for articles. It repeats useful context to make the article body long enough for the stricter articles threshold.</p>
    """

    candidate = extract_aif_turbo_candidate(item=_rss_item(turbo_html), source=_aif_articles_source())

    assert candidate.method == "rss_turbo_structured"
    assert candidate.content_status == "ok"
    assert candidate.quality["is_high_quality"] is True
    assert "turbo_low_quality" not in candidate.extra


def test_aif_articles_candidate_downgrades_short_turbo_without_html_fallback() -> None:
    candidate = extract_aif_turbo_candidate(
        item=_rss_item("<p>One short and incomplete turbo paragraph.</p>"),
        source=_aif_articles_source(),
    )

    assert candidate.method == "rss_turbo_structured"
    assert candidate.content_status == "partial"
    assert candidate.extra["turbo_low_quality"] is True
    assert candidate.quality["reason"] == "turbo_too_short"


def test_bfm_candidate_removes_inline_readalso_without_losing_paragraph_tail() -> None:
    html = """
    <html><body>
      <section class="inner-news article-news">
        <div class="current-article js-mediator-article">
          <p class="about-article">Lead stays metadata, not body content.</p>
          <p>First article paragraph.</p>
          <p>
            <span class="see_also">
              <span class="see_also__title">Читайте также:</span>
              <a class="see_also__link" href="/news/1">Related card title</a>
            </span>
            Important article paragraph after related card.
          </p>
          <p>Final article paragraph.</p>
        </div>
      </section>
    </body></html>
    """

    candidate = extract_candidate(html, _bfm_source())

    assert candidate is not None
    assert candidate.method == "bfm_source_specific_readalso_safe"
    assert candidate.content == (
        "First article paragraph.\n\n"
        "Important article paragraph after related card.\n\n"
        "Final article paragraph."
    )
    assert candidate.extra["source_lead"] == "Lead stays metadata, not body content."
    assert candidate.quality["removed_readalso_blocks"] == 1
    assert "Читайте также" not in candidate.content
    assert "Related card title" not in candidate.content


def test_ria_candidate_accepts_real_short_structured_article() -> None:
    html = """
    <html><body>
      <div class="article__body">
        <div class="article__block" data-type="text">
          <div class="article__text">Первый короткий абзац реальной новости РИА.</div>
        </div>
        <div class="article__block" data-type="text">
          <div class="article__text">Второй короткий абзац с полезным фактом.</div>
        </div>
      </div>
    </body></html>
    """

    current = extract_source_specific(html, _ria_source())
    candidate = extract_candidate(html, _ria_source())

    assert current is not None
    assert current["content"] is None
    assert candidate is not None
    assert candidate.content == (
        "Первый короткий абзац реальной новости РИА.\n\n"
        "Второй короткий абзац с полезным фактом."
    )
    assert candidate.content_status == "partial"
    assert candidate.quality["accepted_short_article"] is True


def test_ria_candidate_rejects_known_chat_comment_noise() -> None:
    html = """
    <html><body>
      <div class="article__body">
        <div class="article__block" data-type="text">
          <div class="article__text">Доступ к чату заблокирован. Чтобы участвовать в дискуссии, войдите.</div>
        </div>
      </div>
    </body></html>
    """

    candidate = extract_candidate(html, _ria_source())

    assert candidate is not None
    assert candidate.content is None
    assert candidate.content_status == "extraction_failed"
    assert candidate.quality["source_specific_blocks"] == 0


def test_ria_candidate_preserves_quote_blocks_in_article_order() -> None:
    html = """
    <html><body>
      <div class="article__body">
        <div class="article__block" data-type="text">
          <div class="article__text">Первый абзац перед цитатой.</div>
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
        <div class="article__block" data-type="text">
          <div class="article__text">Абзац после цитаты.</div>
        </div>
      </div>
    </body></html>
    """

    candidate = extract_candidate(html, _ria_source())

    assert candidate is not None
    assert candidate.content == (
        "Первый абзац перед цитатой.\n\n"
        '"Важная цитата", — написал он.\n\n'
        "Абзац после цитаты."
    )
    assert "Связанная статья" not in candidate.content


def test_candidate_noise_markers_reports_ria_ui_noise() -> None:
    markers = candidate_noise_markers("Заголовок. Доступ к чату заблокирован.")

    assert markers == ["Доступ к чату заблокирован"]
