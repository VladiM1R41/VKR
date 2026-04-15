"""Hooks for source-specific HTML extractors."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from jarvis.db.models import Source


def extract_source_specific(html: str, source: Source) -> dict[str, Any] | None:
    """Return source-specific extraction result when configured."""
    source_key = (source.config or {}).get("source_key")

    if source_key == "rt":
        return _extract_rt_source_specific(html, source)
    if source_key == "ria":
        return _extract_ria_source_specific(html, source)
    if source_key in {"vedomosti_news", "vedomosti_articles"}:
        return _extract_vedomosti_source_specific(html, source)

    return None


def _extract_rt_source_specific(html: str, source: Source) -> dict[str, Any] | None:
    """RT reliably exposes content in summary and article blocks."""
    soup = BeautifulSoup(html, "html.parser")
    strategy = dict((source.config or {}).get("extraction_strategy") or {})
    block_selectors = strategy.get("css_blocks") or [".article__summary", ".article__text"]
    tags_selector = strategy.get("tags_block") or ".article__tags-trends"

    parts: list[str] = []
    for selector in block_selectors:
        for block in soup.select(selector):
            for node in block.select("script, style, figure, noscript, iframe"):
                node.decompose()

            text = block.get_text("\n", strip=True)
            text = _normalize_block_text(text)
            if text:
                parts.append(text)

    content = "\n\n".join(part for part in parts if part).strip()
    extra: dict[str, Any] = {}

    tags_block = soup.select_one(tags_selector)
    if tags_block is not None:
        tags = [
            _normalize_inline_text(anchor.get_text(" ", strip=True))
            for anchor in tags_block.find_all("a")
            if anchor.get_text(" ", strip=True)
        ]
        if tags:
            extra["tags"] = tags

    if len(content) < 200:
        return {"content": None, "extra": extra}

    return {"content": content, "extra": extra}


def _extract_ria_source_specific(html: str, source: Source) -> dict[str, Any] | None:
    """RIA exposes article paragraphs in structured article__block text containers."""
    soup = BeautifulSoup(html, "html.parser")
    strategy = dict((source.config or {}).get("extraction_strategy") or {})
    body_selector = strategy.get("body_selector") or ".article__body"
    block_selector = strategy.get("text_block_selector") or ".article__block[data-type='text'] .article__text"

    body = soup.select_one(body_selector)
    search_root = body if body is not None else soup

    parts: list[str] = []
    for block in search_root.select(block_selector):
        for node in block.select("script, style, figure, noscript, iframe, aside"):
            node.decompose()

        text = block.get_text(" ", strip=True)
        text = _normalize_inline_text(text)
        if text:
            parts.append(text)

    content = "\n\n".join(parts).strip()
    if len(content) < 200:
        return {"content": None, "extra": {}}

    return {"content": content, "extra": {}}


def _extract_vedomosti_source_specific(html: str, source: Source) -> dict[str, Any] | None:
    """Vedomosti stores article body in sequential box-paragraph text blocks."""
    soup = BeautifulSoup(html, "html.parser")
    strategy = dict((source.config or {}).get("extraction_strategy") or {})
    body_selector = strategy.get("body_selector") or ".article-boxes-list"
    text_block_selector = strategy.get("text_block_selector") or ".article-boxes-list__item .box-paragraph__text"
    subtitle_selector = strategy.get("subtitle_selector") or ".article-boxes-list__item .box-paragraph__subtitle"
    lead_selector = strategy.get("lead_selector") or ".article-headline__subtitle"

    body = soup.select_one(body_selector)
    search_root = body if body is not None else soup

    parts: list[str] = []
    lead = soup.select_one(lead_selector)
    if lead is not None:
        lead_text = _normalize_inline_text(lead.get_text(" ", strip=True))
        if lead_text:
            parts.append(lead_text)

    combined_selector = f"{subtitle_selector}, {text_block_selector}"
    for block in search_root.select(combined_selector):
        for node in block.select("script, style, figure, noscript, iframe, aside"):
            node.decompose()

        text = block.get_text(" ", strip=True)
        text = _normalize_inline_text(text)
        if text:
            parts.append(text)

    content = "\n\n".join(parts).strip()
    if len(content) < 200:
        return {"content": None, "extra": {}}

    return {"content": content, "extra": {}}


def _normalize_block_text(text: str) -> str:
    lines = [_normalize_inline_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def _normalize_inline_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.:;!?])", r"\1", text)
    return text
