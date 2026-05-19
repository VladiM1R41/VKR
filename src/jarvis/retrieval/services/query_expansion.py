"""Query expansion using high-PMI collocations from Layer 2."""

from __future__ import annotations

import logging
import re
import time

from jarvis.core.logging import log_event
from jarvis.db.models import Collocation
from jarvis.db.session import SyncSessionLocal


logger = logging.getLogger(__name__)

_MIN_PMI_FOR_EXPANSION = 5.0
_MAX_EXPANSIONS = 3
_MIN_EXPANSION_TERM_LENGTH = 4
_COLLOCATION_TTL_SECONDS = 15 * 60
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9-]+")

_collocation_cache: dict[str, object] = {
    "loaded_at": 0.0,
    "value": [],
}


def clear_collocation_cache() -> None:
    """Clear cached collocations after analytics refresh or in tests."""
    _collocation_cache["loaded_at"] = 0.0
    _collocation_cache["value"] = []


def _load_collocations() -> list[tuple[str, str, float]]:
    """Load collocations with a short TTL instead of process-lifetime caching."""
    now = time.monotonic()
    cached = _collocation_cache.get("value")
    loaded_at = float(_collocation_cache.get("loaded_at") or 0.0)
    if isinstance(cached, list) and cached and now - loaded_at < _COLLOCATION_TTL_SECONDS:
        return cached

    with SyncSessionLocal() as session:
        rows = session.query(
            Collocation.term_a,
            Collocation.term_b,
            Collocation.pmi_score,
        ).filter(
            Collocation.pmi_score >= _MIN_PMI_FOR_EXPANSION,
        ).order_by(
            Collocation.pmi_score.desc(),
        ).limit(500).all()

    collocations = [(a.lower(), b.lower(), float(score)) for a, b, score in rows if a and b and score is not None]
    _collocation_cache["loaded_at"] = now
    _collocation_cache["value"] = collocations
    return collocations


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def expand_query_with_collocations(query: str) -> list[str]:
    """Expand query by exact token matches, not substring matches."""
    collocations = _load_collocations()
    if not collocations:
        return []

    query_tokens = _tokens(query)
    query_lower = " ".join(query_tokens)
    expansions: list[str] = []
    seen: set[str] = set()

    for term_a, term_b, _pmi in collocations:
        if len(term_a) < _MIN_EXPANSION_TERM_LENGTH or len(term_b) < _MIN_EXPANSION_TERM_LENGTH:
            continue
        phrase = f"{term_a} {term_b}"
        if phrase in seen:
            continue

        phrase_tokens = {term_a, term_b}
        matched = phrase_tokens & query_tokens
        full_phrase_already_present = phrase in query_lower or phrase_tokens <= query_tokens
        if matched and not full_phrase_already_present:
            expansions.append(phrase)
            seen.add(phrase)

        if len(expansions) >= _MAX_EXPANSIONS:
            break

    if expansions:
        log_event(logger, logging.INFO, "query_expanded", original=query, expansions=expansions)
    return expansions
