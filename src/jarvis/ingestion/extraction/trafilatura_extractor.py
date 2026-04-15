"""HTML extraction cascade based on trafilatura."""

from __future__ import annotations

import trafilatura


PRECISION_MIN_LEN = 200
RECALL_MIN_LEN = 100


def extract_with_precision(html: str) -> str | None:
    """Default extraction mode for HTML sources."""
    content = trafilatura.extract(
        html,
        favor_precision=True,
        include_comments=False,
        include_tables=False,
        deduplicate=True,
    )
    if content and len(content.strip()) >= PRECISION_MIN_LEN:
        return content.strip()
    return None


def extract_with_recall(html: str) -> str | None:
    """Fallback extraction mode for short or noisy pages."""
    content = trafilatura.extract(
        html,
        favor_recall=True,
        include_comments=False,
        include_tables=False,
        deduplicate=True,
    )
    if content and len(content.strip()) >= RECALL_MIN_LEN:
        return content.strip()
    return None

