"""Structured extraction helpers for RSS-first sources."""

from __future__ import annotations

import html
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from jarvis.ingestion.extraction.postprocess import apply_postprocess_rules, apply_pre_extraction_rules


def extract_rss_fulltext(
    *,
    item: Tag,
    method: str,
    config: dict[str, Any],
    full_text_html: str | None,
    description_html: str | None,
    thumbnail_url: str | None = None,
) -> dict[str, Any]:
    """Extract full text directly from RSS payload when the source supports it."""
    if method == "rss_yandex_fulltext":
        return _extract_from_direct_html_tag(
            item=item,
            tag_name=config.get("full_text_tag", "yandex:full-text"),
            method=method,
            description_html=description_html,
            config=config,
        )

    if method == "rss_custom_namespace":
        return _extract_from_direct_html_tag(
            item=item,
            tag_name=config.get("full_text_tag", ""),
            method=method,
            description_html=description_html,
            config=config,
        )

    if method == "rss_description_html":
        return _extract_ixbt_description(
            html_fragment=full_text_html or description_html,
            config=config,
        )

    if method == "rss_turbo_structured":
        return _extract_aif_turbo_structured(
            item=item,
            turbo_html=full_text_html,
            description_html=description_html,
            config=config,
            thumbnail_url=thumbnail_url,
        )

    return {
        "content": None,
        "raw_content": None,
        "raw_format": None,
        "content_status": "partial",
        "extraction_method": None,
        "extra": {},
    }


def _extract_from_direct_html_tag(
    *,
    item: Tag,
    tag_name: str,
    method: str,
    description_html: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    if not tag_name:
        return _empty_result()

    tag = _find_direct_tag(item, tag_name)
    if tag is None:
        return _fallback_from_description(description_html)

    raw_html = tag.decode_contents().strip()
    if not raw_html:
        return _fallback_from_description(description_html)

    prepared_html = apply_pre_extraction_rules(raw_html, list(config.get("postprocess_rules") or []))
    content = _html_fragment_to_text(prepared_html)
    content, _ = apply_postprocess_rules(
        content=content,
        snippet_lead=None,
        rules=list(config.get("postprocess_rules") or []),
    )
    content = (content or "").strip() or None

    if not content:
        return _fallback_from_description(description_html)

    return {
        "content": content,
        "raw_content": raw_html,
        "raw_format": "html",
        "content_status": "ok",
        "extraction_method": method,
        "extra": {},
    }


def _find_direct_tag(item: Tag, tag_name: str) -> Tag | None:
    """Find a direct child tag by literal name, tolerating namespace normalization."""
    expected = tag_name.strip()
    expected_suffix = expected.split(":", 1)[-1]

    for child in item.children:
        child_name = getattr(child, "name", None)
        if not child_name:
            continue
        if child_name == expected or child_name == expected_suffix:
            return child
    return None


def _extract_ixbt_description(*, html_fragment: str | None, config: dict[str, Any]) -> dict[str, Any]:
    if not html_fragment:
        return _empty_result()

    raw_html = html_fragment.strip()
    raw_soup = BeautifulSoup(html.unescape(raw_html), "html.parser")

    thumbnail = None
    first_img = raw_soup.find("img")
    if first_img and first_img.get("src"):
        thumbnail = first_img.get("src", "").strip() or None

    prepared_html = apply_pre_extraction_rules(raw_html, list(config.get("postprocess_rules") or []))
    soup = BeautifulSoup(html.unescape(prepared_html), "html.parser")

    content = soup.get_text("\n", strip=True)
    content, _ = apply_postprocess_rules(
        content=content,
        snippet_lead=None,
        rules=list(config.get("postprocess_rules") or []),
    )
    content = _normalize_multiline_text(content or "")
    if not content:
        return _empty_result()

    extra: dict[str, Any] = {}
    if thumbnail:
        extra["thumbnail"] = thumbnail

    return {
        "content": content,
        "raw_content": raw_html,
        "raw_format": "html",
        "content_status": "ok",
        "extraction_method": "rss_description_html",
        "extra": extra,
    }


def _extract_aif_turbo_structured(
    *,
    item: Tag,
    turbo_html: str | None,
    description_html: str | None,
    config: dict[str, Any],
    thumbnail_url: str | None,
) -> dict[str, Any]:
    primary = _extract_turbo_structured_html(
        html_fragment=turbo_html,
        config=config,
        thumbnail_url=thumbnail_url,
    )
    if config.get("source_key") == "aif_articles":
        yandex_text = _extract_from_direct_html_tag(
            item=item,
            tag_name=config.get("fallback_full_text_tag", "yandex:full-text"),
            method="rss_yandex_fulltext",
            description_html=description_html,
            config=config,
        )
        if yandex_text["content"]:
            yandex_text["extra"] = {
                **(primary.get("extra") or {}),
                **(yandex_text.get("extra") or {}),
            }
            return yandex_text

    if primary["content"]:
        return primary

    fallback_tag = config.get("fallback_full_text_tag")
    if fallback_tag:
        fallback = _extract_from_direct_html_tag(
            item=item,
            tag_name=fallback_tag,
            method="rss_yandex_fulltext_fallback",
            description_html=description_html,
            config=config,
        )
        if fallback["content"]:
            return fallback

    if primary["raw_content"]:
        return primary

    return _fallback_from_description(description_html)


def _extract_turbo_structured_html(
    *,
    html_fragment: str | None,
    config: dict[str, Any],
    thumbnail_url: str | None,
) -> dict[str, Any]:
    if not html_fragment:
        return _empty_result()

    raw_html = html_fragment.strip()
    prepared_html = apply_pre_extraction_rules(raw_html, list(config.get("postprocess_rules") or []))
    soup = BeautifulSoup(html.unescape(prepared_html), "html.parser")

    blocks: list[dict[str, Any]] = []
    text_parts: list[str] = []
    inline_images: list[dict[str, Any]] = []
    headings: list[str] = []
    seen_images: set[str] = set()
    thumbnail_norm = (thumbnail_url or "").strip()

    for child in soup.contents:
        name = _tag_name(child)
        if not name:
            continue

        if name == "header" or _is_widget(child) or _is_related_feed_block(child) or _is_ad_placeholder(child):
            continue

        if name in {"h2", "h3", "h4"}:
            heading = _clean_tag_text(child)
            if heading:
                blocks.append({"type": "heading", "level": int(name[1]), "text": heading})
                headings.append(heading)
                text_parts.append(heading)
            continue

        if name == "p":
            slider_images = _extract_images_from_slider(child, seen_images, thumbnail_norm)
            if slider_images:
                blocks.extend(slider_images)
                inline_images.extend(slider_images)

            paragraph = _extract_paragraph_text(child)
            if paragraph:
                blocks.append({"type": "paragraph", "text": paragraph})
                text_parts.append(paragraph)
            continue

        if name == "figure":
            image_block = _figure_to_image_block(child, seen_images, thumbnail_norm)
            if image_block:
                blocks.append(image_block)
                inline_images.append(image_block)
            continue

    content = "\n\n".join(text_parts).strip() or None
    if not content:
        return {
            "content": None,
            "raw_content": raw_html,
            "raw_format": "html",
            "content_status": "partial",
            "extraction_method": None,
            "extra": {
                "content_blocks": blocks,
                "inline_images": inline_images,
                "turbo_headings": headings,
            },
        }

    return {
        "content": content,
        "raw_content": raw_html,
        "raw_format": "html",
        "content_status": "ok",
        "extraction_method": "rss_turbo_structured",
        "extra": {
            "content_blocks": blocks,
            "inline_images": inline_images,
            "turbo_headings": headings,
        },
    }


def _fallback_from_description(description_html: str | None) -> dict[str, Any]:
    if not description_html:
        return _empty_result()
    content = _html_fragment_to_text(description_html)
    content = content.strip() or None
    if not content:
        return _empty_result()
    return {
        "content": content,
        "raw_content": description_html.strip(),
        "raw_format": "html",
        "content_status": "partial",
        "extraction_method": "rss_description_fallback",
        "extra": {},
    }


def _tag_name(tag: Any) -> str:
    return (getattr(tag, "name", "") or "").lower()


def _is_widget(tag: Tag) -> bool:
    return _tag_name(tag) in {"extretellwidget", "ext24smiwidget", "extsvknativewidget"}


def _is_related_feed_block(tag: Tag) -> bool:
    return _tag_name(tag) == "div" and tag.get("data-block") == "feed"


def _is_ad_placeholder(tag: Tag) -> bool:
    return _tag_name(tag) == "figure" and bool(tag.get("data-turbo-ad-id"))


def _clean_tag_text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    text = tag.get_text(" ", strip=True)
    text = html.unescape(text)
    return _normalize_inline_spacing(text)


def _extract_paragraph_text(tag: Tag) -> str:
    paragraph = BeautifulSoup(str(tag), "html.parser")

    for nested in paragraph.find_all("div"):
        if nested.get("data-block") == "slider":
            nested.decompose()

    for nested in paragraph.find_all("figure"):
        nested.decompose()

    for br in paragraph.find_all("br"):
        br.replace_with("\n")

    text = paragraph.get_text(" ", strip=True)
    text = html.unescape(text)
    return _normalize_inline_spacing(text)


def _extract_images_from_slider(
    tag: Tag,
    seen_images: set[str],
    thumbnail_url: str,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for slider in tag.find_all("div"):
        if slider.get("data-block") != "slider":
            continue
        for figure in slider.find_all("figure"):
            image_block = _figure_to_image_block(figure, seen_images, thumbnail_url)
            if image_block:
                blocks.append(image_block)
    return blocks


def _figure_to_image_block(
    figure: Tag,
    seen_images: set[str],
    thumbnail_url: str,
) -> dict[str, Any] | None:
    img = figure.find("img")
    if not img:
        return None

    src = (img.get("src") or "").strip()
    if not src or src == thumbnail_url or src in seen_images:
        return None
    seen_images.add(src)

    caption = _clean_tag_text(figure.find("figcaption"))
    return {
        "type": "image",
        "src": src,
        "caption": caption or None,
    }


def _html_fragment_to_text(raw_html: str) -> str:
    soup = BeautifulSoup(html.unescape(raw_html), "html.parser")
    block_text = _extract_block_text(soup)
    if block_text:
        return _normalize_multiline_text(block_text)

    text = soup.get_text(" ", strip=True)
    text = html.unescape(text)
    text = _normalize_inline_spacing(text)
    return _normalize_multiline_text(text)


def _extract_block_text(soup: BeautifulSoup) -> str:
    block_names = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}
    blocks: list[str] = []

    for tag in soup.find_all(block_names):
        text = tag.get_text(" ", strip=True)
        text = html.unescape(text)
        text = _normalize_inline_spacing(text)
        if text:
            blocks.append(text)

    return "\n".join(blocks).strip()


def _normalize_inline_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([(\[{])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]}])", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_multiline_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    filtered = [line for line in lines if line]
    return "\n".join(filtered).strip()


def _empty_result() -> dict[str, Any]:
    return {
        "content": None,
        "raw_content": None,
        "raw_format": None,
        "content_status": "partial",
        "extraction_method": None,
        "extra": {},
    }
