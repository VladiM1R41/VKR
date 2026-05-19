"""HTML extraction cascade based on trafilatura."""

from __future__ import annotations

from functools import lru_cache
import inspect

import trafilatura


PRECISION_MIN_LEN = 200
RECALL_MIN_LEN = 100
TARGET_LANGUAGE = "ru"


@lru_cache(maxsize=1)
def _supports_target_language() -> bool:
    """Return whether the installed trafilatura.extract supports target_language."""
    try:
        return "target_language" in inspect.signature(trafilatura.extract).parameters
    except (TypeError, ValueError):
        return False


def _extract(html: str, **kwargs) -> str | None:
    if _supports_target_language():
        kwargs.setdefault("target_language", TARGET_LANGUAGE)
    return trafilatura.extract(html, **kwargs)


def extract_with_precision(html: str) -> str | None:
    """Default extraction mode for HTML sources."""
    content = _extract(
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
    content = _extract(
        html,
        favor_recall=True,
        include_comments=False,
        include_tables=False,
        deduplicate=True,
    )
    if content and len(content.strip()) >= RECALL_MIN_LEN:
        return content.strip()
    return None
