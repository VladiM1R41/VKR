"""Pre/post-extraction cleanup rules driven by ``sources.config``."""

from __future__ import annotations

import html
import re
from typing import Any

from bs4 import BeautifulSoup


def apply_pre_extraction_rules(html_content: str, rules: list[dict[str, Any]]) -> str:
    """Apply DOM-level cleanup before running text extraction."""
    if not html_content:
        return html_content

    soup = BeautifulSoup(html.unescape(html_content), "html.parser")

    for rule in rules:
        rule_type = rule.get("type")
        if rule_type == "bs4_decompose_selector":
            selector = rule.get("selector")
            if not selector:
                continue
            for node in soup.select(selector):
                node.decompose()
        elif rule_type == "bs4_decompose_figures_with_data_attr":
            attr = rule.get("data_attr") or rule.get("attr")
            if not attr:
                continue
            for node in soup.find_all("figure", attrs={attr: True}):
                node.decompose()

    return str(soup)


def apply_postprocess_rules(
    *,
    content: str | None,
    snippet_lead: str | None,
    rules: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Apply text-level cleanup after extraction."""
    processed_content = content
    processed_snippet = snippet_lead

    for rule in rules:
        if _is_pre_extraction_rule(rule):
            continue

        fields = set(rule.get("fields") or ["content"])
        if "content" in fields and processed_content is not None:
            processed_content = _apply_text_rule(processed_content, rule)
        if "snippet_lead" in fields and processed_snippet is not None:
            processed_snippet = _apply_text_rule(processed_snippet, rule)

    return processed_content, processed_snippet


def _is_pre_extraction_rule(rule: dict[str, Any]) -> bool:
    rule_type = rule.get("type", "")
    return rule_type.startswith("bs4_decompose_")


def _apply_text_rule(text: str, rule: dict[str, Any]) -> str:
    rule_type = rule.get("type")

    if rule_type == "regex_strip_tail":
        pattern = rule.get("pattern")
        if not pattern:
            return text
        return re.sub(pattern, "", text, flags=_parse_regex_flags(rule.get("flags"))).strip()

    if rule_type == "remove_lines_starting_with":
        prefixes = [str(prefix) for prefix in rule.get("prefixes") or [] if prefix]
        if not prefixes:
            return text
        return _rebuild_lines(
            text,
            lambda line: not any(line.strip().startswith(prefix) for prefix in prefixes),
        )

    if rule_type == "remove_lines_matching":
        patterns = [
            str(pattern)
            for pattern in (rule.get("patterns") or ([rule.get("pattern")] if rule.get("pattern") else []))
            if pattern
        ]
        if not patterns:
            return text
        regexes = [re.compile(pattern) for pattern in patterns]
        return _rebuild_lines(
            text,
            lambda line: not any(regex.search(line.strip()) for regex in regexes),
        )

    if rule_type == "html_unescape":
        return html.unescape(text).strip()

    return text


def _rebuild_lines(text: str, keep_line: callable) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and keep_line(line)]
    return "\n".join(lines).strip()


def _parse_regex_flags(flags: Any) -> int:
    if not flags:
        return re.S

    if isinstance(flags, int):
        return flags

    result = 0
    for char in str(flags).lower():
        if char == "s":
            result |= re.S
        elif char == "i":
            result |= re.I
        elif char == "m":
            result |= re.M

    return result or re.S
