"""Experimental source-specific extractors for Group E validation.

These helpers are intentionally not imported by the production ingestion path.
They let us compare candidate extraction strategies against the current Layer 1
pipeline before deciding whether a source-specific change is safe to promote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from jarvis.db.models import Source
from jarvis.ingestion.extraction.postprocess import apply_postprocess_rules, apply_pre_extraction_rules
from jarvis.ingestion.extraction.rss_fulltext import extract_rss_fulltext
from jarvis.ingestion.extraction.trafilatura_extractor import extract_with_precision


RIA_UI_NOISE_PATTERNS = (
    "Доступ к чату заблокирован",
    "Чтобы участвовать в дискуссии",
    "Обсуждение закрыто",
    "Заголовок открываемого материала",
    "Войдите, чтобы оставить комментарий",
)


@dataclass(slots=True)
class CandidateExtraction:
    """A comparable extraction result for source-specific experiments."""

    source_key: str
    method: str
    content: str | None
    content_status: str
    extra: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)


def extract_candidate(html: str, source: Source) -> CandidateExtraction | None:
    """Dispatch an experimental extractor by ``source.config.source_key``."""

    source_key = str((source.config or {}).get("source_key") or "").strip()
    if source_key == "ria":
        return extract_ria_candidate(html, source)
    if source_key == "bfm":
        return extract_bfm_candidate(html, source)
    return None


def extract_bfm_candidate(html: str, source: Source) -> CandidateExtraction:
    """BFM candidate: remove inline read-also cards without dropping paragraph text."""

    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("section.inner-news.article-news .current-article.js-mediator-article")
    if root is None:
        root = soup.select_one(".current-article.js-mediator-article")

    if root is None:
        return CandidateExtraction(
            source_key="bfm",
            method="bfm_source_specific_readalso_safe",
            content=None,
            content_status="extraction_failed",
            quality={"reason": "article_root_not_found"},
        )

    lead_text: str | None = None
    parts: list[str] = []
    removed_readalso_blocks = 0
    inspected_blocks = 0

    for block in root.find_all(["p", "blockquote"], recursive=False):
        inspected_blocks += 1
        if "about-article" in (block.get("class") or []):
            lead_text = _extract_clean_block_text(block) or None
            continue

        clone = BeautifulSoup(str(block), "html.parser")
        for noisy_node in clone.select(".see_also, script, style, figure, noscript, iframe"):
            if "see_also" in (noisy_node.get("class") or []):
                removed_readalso_blocks += 1
            noisy_node.decompose()

        text = _normalize_inline_text(clone.get_text(" ", strip=True))
        if text:
            parts.append(text)

    content = "\n\n".join(parts).strip() or None
    content_length = len(content or "")
    extra: dict[str, Any] = {}
    if lead_text:
        extra["source_lead"] = lead_text

    return CandidateExtraction(
        source_key="bfm",
        method="bfm_source_specific_readalso_safe",
        content=content,
        content_status="ok" if content_length >= 200 else "partial",
        extra=extra,
        quality={
            "content_length": content_length,
            "body_blocks": len(parts),
            "inspected_blocks": inspected_blocks,
            "removed_readalso_blocks": removed_readalso_blocks,
            "source_lead_length": len(lead_text or ""),
        },
    )


def extract_aif_turbo_candidate(
    *,
    item: Tag,
    source: Source,
    html_content: str | None = None,
    thumbnail_url: str | None = None,
) -> CandidateExtraction:
    """AIF articles candidate: keep good turbo, fallback only for low-quality turbo.

    ``aif_articles`` is RSS-first and usually excellent because ``turbo:content``
    preserves headings, paragraphs, images and related metadata. The defect is
    that a tiny or punctuation-only turbo body is currently still marked as
    ``ok``. This candidate keeps the current turbo result when it passes the
    source-specific gate, otherwise tries clean HTML fallback and records the
    low-quality turbo provenance in ``extra``.
    """

    config = dict(source.config or {})
    description_html = _get_direct_tag_html(item, "description")
    full_text_html = _get_direct_tag_html(item, config.get("full_text_tag"))
    current = extract_rss_fulltext(
        item=item,
        method=config.get("full_text_method", "rss_turbo_structured"),
        config=config,
        full_text_html=full_text_html,
        description_html=description_html,
        thumbnail_url=thumbnail_url,
    )
    source_key = str(config.get("source_key") or "")
    quality = _assess_aif_turbo_quality(current.get("content"), current.get("extra") or {}, source_key)
    current_extra = dict(current.get("extra") or {})

    if quality["is_high_quality"]:
        return CandidateExtraction(
            source_key=source_key,
            method=str(current.get("extraction_method") or "rss_turbo_structured"),
            content=current.get("content"),
            content_status=str(current.get("content_status") or "ok"),
            extra=current_extra,
            quality=quality,
        )

    fallback_content = _extract_aif_html_fallback(html_content, config)
    if _html_fallback_is_better(fallback_content, current.get("content")):
        extra = dict(current_extra)
        extra.update(
            {
                "turbo_low_quality": True,
                "turbo_original_length": len(current.get("content") or ""),
                "fallback_reason": quality["reason"],
                "fallback_from": current.get("extraction_method") or "rss_turbo_structured",
            }
        )
        return CandidateExtraction(
            source_key=source_key,
            method="html_fallback_after_turbo_low_quality",
            content=fallback_content,
            content_status="ok",
            extra=extra,
            quality={**quality, "html_fallback_length": len(fallback_content or ""), "used_html_fallback": True},
        )

    return CandidateExtraction(
        source_key=source_key,
        method=str(current.get("extraction_method") or "rss_turbo_structured"),
        content=current.get("content"),
        content_status="partial",
        extra={
            **current_extra,
            "turbo_low_quality": True,
            "turbo_original_length": len(current.get("content") or ""),
            "fallback_reason": quality["reason"],
        },
        quality={**quality, "html_fallback_length": len(fallback_content or ""), "used_html_fallback": False},
    )


def extract_ria_candidate(html: str, source: Source) -> CandidateExtraction:
    """RIA candidate: trust structured article text blocks even for short news.

    The current production extractor rejects valid short RIA articles when the
    extracted body is under the global 200-character threshold. This candidate
    keeps the same trusted selectors, but accepts short body text when it comes
    from real ``article__block[data-type=text]`` nodes and does not match known
    comment/chat UI noise.
    """

    soup = BeautifulSoup(html, "html.parser")
    strategy = dict((source.config or {}).get("extraction_strategy") or {})
    body_selector = strategy.get("body_selector") or ".article__body"
    block_selector = strategy.get("text_block_selector") or ".article__block[data-type='text'] .article__text"

    body = soup.select_one(body_selector)
    search_root: Tag | BeautifulSoup = body if body is not None else soup

    parts: list[str] = []
    article_blocks = search_root.select(".article__block")
    if article_blocks:
        for block in article_blocks:
            block_type = str(block.get("data-type") or "").strip()
            if block_type == "text":
                text_node = block.select_one(".article__text") or block
            elif block_type == "quote":
                text_node = block.select_one(".article__quote-text") or block.select_one(".article__quote") or block
            else:
                continue

            text = _extract_clean_block_text(text_node)
            if text and not _looks_like_ria_ui_noise(text):
                parts.append(text)
    else:
        for block in search_root.select(block_selector):
            text = _extract_clean_block_text(block)
            if text and not _looks_like_ria_ui_noise(text):
                parts.append(text)

    content = "\n\n".join(parts).strip() or None
    block_count = len(parts)
    content_length = len(content or "")
    has_noise = bool(content and _looks_like_ria_ui_noise(content))

    if content and block_count >= 1 and content_length >= 40 and not has_noise:
        return CandidateExtraction(
            source_key="ria",
            method="ria_source_specific_short_safe",
            content=content,
            content_status="ok" if content_length >= 200 else "partial",
            quality={
                "source_specific_blocks": block_count,
                "content_length": content_length,
                "accepted_short_article": content_length < 200,
                "noise_rejected": False,
            },
        )

    return CandidateExtraction(
        source_key="ria",
        method="ria_source_specific_short_safe",
        content=None,
        content_status="extraction_failed",
        quality={
            "source_specific_blocks": block_count,
            "content_length": content_length,
            "accepted_short_article": False,
            "noise_rejected": has_noise,
        },
    )


def candidate_noise_markers(content: str | None) -> list[str]:
    """Return known noise markers present in extracted text."""

    if not content:
        return []
    return [marker for marker in RIA_UI_NOISE_PATTERNS if marker.lower() in content.lower()]


def starts_with_title(content: str | None, title: str | None) -> bool:
    """Detect the common extraction defect where content starts with title."""

    if not content or not title:
        return False
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    return _normalize_for_compare(first_line) == _normalize_for_compare(title)


def _looks_like_ria_ui_noise(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in RIA_UI_NOISE_PATTERNS)


def _assess_aif_turbo_quality(content: str | None, extra: dict[str, Any], source_key: str) -> dict[str, Any]:
    text = content or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    meaningful_lines = [line for line in lines if _meaningful_text_length(line) >= 40]
    punctuation_only_lines = [line for line in lines if line and not re.search(r"[0-9A-Za-zА-Яа-яЁё]", line)]
    content_blocks = list(extra.get("content_blocks") or [])
    paragraph_blocks = [block for block in content_blocks if block.get("type") == "paragraph"]
    min_length = 500 if source_key == "aif_articles" else 200

    reason = "ok"
    is_high_quality = True
    if len(text) < min_length:
        reason = "turbo_too_short"
        is_high_quality = False
    elif len(meaningful_lines) < 2:
        reason = "not_enough_meaningful_paragraphs"
        is_high_quality = False
    elif punctuation_only_lines:
        reason = "punctuation_only_paragraph"
        is_high_quality = False
    elif source_key == "aif_articles" and len(paragraph_blocks) < 2:
        reason = "not_enough_turbo_paragraph_blocks"
        is_high_quality = False

    return {
        "is_high_quality": is_high_quality,
        "reason": reason,
        "content_length": len(text),
        "line_count": len(lines),
        "meaningful_line_count": len(meaningful_lines),
        "paragraph_block_count": len(paragraph_blocks),
        "punctuation_only_line_count": len(punctuation_only_lines),
        "min_length": min_length,
    }


def _extract_aif_html_fallback(html_content: str | None, config: dict[str, Any]) -> str | None:
    if not html_content:
        return None

    rules = list(config.get("postprocess_rules") or [])
    prepared_html = apply_pre_extraction_rules(html_content, rules)
    content = extract_with_precision(prepared_html)
    content, _ = apply_postprocess_rules(content=content, snippet_lead=None, rules=rules)
    return (content or "").strip() or None


def _html_fallback_is_better(fallback_content: str | None, current_content: str | None) -> bool:
    if not fallback_content:
        return False
    current_length = len(current_content or "")
    fallback_length = len(fallback_content)
    return fallback_length >= 500 and fallback_length >= max(current_length * 3, current_length + 400)


def _get_direct_tag_html(item: Tag, tag_name: str | None) -> str | None:
    if not tag_name:
        return None

    expected = str(tag_name).strip()
    expected_suffix = expected.split(":", 1)[-1]
    for child in item.children:
        child_name = getattr(child, "name", None)
        if child_name == expected or child_name == expected_suffix:
            raw = child.decode_contents().strip()
            return raw or None
    return None


def _meaningful_text_length(text: str) -> int:
    return len(re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", text or ""))


def _extract_clean_block_text(block: Tag) -> str:
    for node in block.select("script, style, figure, noscript, iframe, aside"):
        node.decompose()

    text = block.get_text(" ", strip=True)
    return _normalize_inline_text(text)


def _normalize_inline_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.:;!?])", r"\1", text)
    return text


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()
