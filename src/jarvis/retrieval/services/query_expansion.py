"""Query expansion using collocations from Layer 2.

If user queries "ставка", expand to "ключевая ставка" if that collocation
has high PMI score (from Layer 2 batch analytics).

This improves recall without requiring LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging
import re

from jarvis.core.logging import log_event
from jarvis.db.models import Collocation
from jarvis.db.session import SyncSessionLocal


logger = logging.getLogger(__name__)

_MIN_PMI_FOR_EXPANSION = 5.0  # Strong association only
_MAX_EXPANSIONS = 3


@lru_cache(maxsize=1)
def _load_collocations() -> list[tuple[str, str, float]]:
    """Load collocations with PMI > threshold from PostgreSQL.

    Returns list of (term_a, term_b, pmi_score).
    Cached for performance.
    """
    with SyncSessionLocal() as session:
        rows = session.query(
            Collocation.term_a,
            Collocation.term_b,
            Collocation.pmi_score,
        ).filter(
            Collocation.pmi_score >= _MIN_PMI_FOR_EXPANSION,
        ).order_by(
            Collocation.pmi_score.desc(),
        ).limit(100).all()

        return [(a, b, score) for a, b, score in rows if score is not None]


def expand_query_with_collocations(query: str) -> list[str]:
    """Expand query using high-PMI collocations.

    If query contains one term of a collocation, add the full phrase.
    Example: "ставка" → "ключевая ставка" (PMI=8.2).

    Args:
        query: User query (preferably lemmatized).

    Returns:
        List of expansion phrases (empty if no collocations match).
    """
    collocations = _load_collocations()
    if not collocations:
        return []

    query_lower = query.lower()
    expansions: list[str] = []
    seen: set[str] = set()

    for term_a, term_b, pmi in collocations:
        phrase = f"{term_a} {term_b}"
        if phrase in seen:
            continue

        # Check if query contains either term
        a_in_query = term_a.lower() in query_lower
        b_in_query = term_b.lower() in query_lower

        # Expand if one term is present but not the full phrase
        if (a_in_query or b_in_query) and phrase.lower() not in query_lower:
            expansions.append(phrase)
            seen.add(phrase)

        if len(expansions) >= _MAX_EXPANSIONS:
            break

    if expansions:
        log_event(
            logger,
            logging.INFO,
            "query_expanded",
            original=query,
            expansions=expansions,
        )

    return expansions
