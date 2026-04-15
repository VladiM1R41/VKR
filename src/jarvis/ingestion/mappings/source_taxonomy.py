"""Mapping of source-specific taxonomies into CHECK-safe Layer 1 fields."""

from __future__ import annotations


ALLOWED_CONTENT_TYPES = {"news", "analysis", "press_release", "opinion"}
ALLOWED_INFORMATION_TYPES = {"breaking", "daily", "analytics", "reference"}


CONTENT_TYPE_MAPPINGS: dict[str, dict[str, str]] = {
    "ria": {
        "article": "news",
        "analytics": "analysis",
        "default": "news",
    },
    "rbc": {
        "short_news": "news",
        "article": "analysis",
        "default": "news",
    },
    "aif_news": {
        "default": "news",
    },
    "aif_articles": {
        "default": "analysis",
    },
    "_default": {
        "default": "news",
    },
}


INFORMATION_TYPE_MAPPINGS: dict[str, dict[str, str]] = {
    "aif_news": {
        "analytical": "analytics",
        "default": "daily",
    },
    "aif_articles": {
        "analytical": "analytics",
        "default": "analytics",
    },
    "_default": {
        "default": "daily",
    },
}


def map_content_type(source_key: str, raw_value: str | None, fallback: str) -> str:
    """Map source taxonomy into the DB CHECK domain for news.content_type."""
    mapping = CONTENT_TYPE_MAPPINGS.get(source_key, CONTENT_TYPE_MAPPINGS["_default"])
    normalized_raw = (raw_value or "").strip().lower()
    normalized_fallback = (fallback or "").strip().lower()

    candidate = mapping.get(normalized_raw) if normalized_raw else None
    if candidate in ALLOWED_CONTENT_TYPES:
        return candidate

    if normalized_fallback in ALLOWED_CONTENT_TYPES:
        return normalized_fallback

    default_candidate = mapping.get("default", "news")
    if default_candidate in ALLOWED_CONTENT_TYPES:
        return default_candidate

    return "news"


def map_information_type(source_key: str, raw_value: str | None, fallback: str) -> str:
    """Map source taxonomy into the DB CHECK domain for news.information_type."""
    mapping = INFORMATION_TYPE_MAPPINGS.get(source_key, INFORMATION_TYPE_MAPPINGS["_default"])
    normalized_raw = (raw_value or "").strip().lower()
    normalized_fallback = (fallback or "").strip().lower()

    candidate = mapping.get(normalized_raw) if normalized_raw else None
    if candidate in ALLOWED_INFORMATION_TYPES:
        return candidate

    if normalized_fallback in ALLOWED_INFORMATION_TYPES:
        return normalized_fallback

    default_candidate = mapping.get("default", "daily")
    if default_candidate in ALLOWED_INFORMATION_TYPES:
        return default_candidate

    return "daily"

