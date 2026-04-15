"""Rule-based routing helpers for Layer 1."""

from __future__ import annotations


BREAKING_MARKERS_UPPER = (
    "СРОЧНО",
    "BREAKING",
    "МОЛНИЯ",
    "ВНИМАНИЕ",
    "[СРОЧНО]",
    "[BREAKING]",
    "⚡",
    "🚨",
)


def detect_breaking(title: str | None) -> bool:
    """Return True when the title carries an explicit breaking-news marker."""
    if not title:
        return False

    title_upper = title.upper()
    return any(marker in title_upper for marker in BREAKING_MARKERS_UPPER)

