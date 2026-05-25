"""Query expansion using high-PMI collocations from Layer 2."""

from __future__ import annotations

import logging
import re
import time

from jarvis.core.logging import log_event
from jarvis.db.models import Collocation
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.ir.quality_terms import (
    collocation_expansion_score,
    is_informative_bigram,
    is_query_expansion_term,
)


logger = logging.getLogger(__name__)

_MIN_PMI_FOR_EXPANSION = 5.0
_MIN_FREQUENCY_FOR_EXPANSION = 7
_MAX_EXPANSIONS = 3
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


def _load_collocations() -> list[tuple[str, str, float, int]]:
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
            Collocation.frequency,
        ).filter(
            Collocation.pmi_score >= _MIN_PMI_FOR_EXPANSION,
            Collocation.frequency >= _MIN_FREQUENCY_FOR_EXPANSION,
        ).order_by(
            Collocation.frequency.desc(),
            Collocation.pmi_score.desc(),
        ).limit(1000).all()

    collocations = [
        (a.lower(), b.lower(), float(score), int(frequency))
        for a, b, score, frequency in rows
        if a and b and score is not None and is_informative_bigram(a, b)
    ]
    collocations.sort(
        key=lambda item: collocation_expansion_score(pmi_score=item[2], frequency=item[3]),
        reverse=True,
    )
    _collocation_cache["loaded_at"] = now
    _collocation_cache["value"] = collocations
    return collocations


def _unpack_collocation(item: tuple) -> tuple[str, str, float, int]:
    """Support old 3-tuples in tests while production uses frequency-aware rows."""

    if len(item) == 3:
        term_a, term_b, pmi = item
        return str(term_a), str(term_b), float(pmi), _MIN_FREQUENCY_FOR_EXPANSION
    term_a, term_b, pmi, frequency = item[:4]
    return str(term_a), str(term_b), float(pmi), int(frequency)


def _is_expansion_candidate(term_a: str, term_b: str, frequency: int) -> bool:
    if frequency < _MIN_FREQUENCY_FOR_EXPANSION:
        return False
    if not is_informative_bigram(term_a, term_b):
        return False
    return is_query_expansion_term(term_a) and is_query_expansion_term(term_b)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _contains_known_phrase(query_tokens: set[str], collocations: list[tuple]) -> bool:
    if len(query_tokens) < 2:
        return False
    for item in collocations:
        term_a, term_b, _pmi, frequency = _unpack_collocation(item)
        if not _is_expansion_candidate(term_a, term_b, frequency):
            continue
        if {term_a, term_b} <= query_tokens:
            return True
    return False


def expand_query_with_collocations(query: str) -> list[str]:
    """Expand query by exact token matches, not substring matches."""
    collocations = _load_collocations()
    if not collocations:
        return []

    query_tokens = _tokens(query)
    if _contains_known_phrase(query_tokens, collocations):
        return []

    expansions: list[str] = []
    seen: set[str] = set()

    for item in collocations:
        term_a, term_b, _pmi, frequency = _unpack_collocation(item)
        if not _is_expansion_candidate(term_a, term_b, frequency):
            continue
        phrase = f"{term_a} {term_b}"
        if phrase in seen:
            continue

        phrase_tokens = {term_a, term_b}
        matched = phrase_tokens & query_tokens
        full_phrase_already_present = phrase_tokens <= query_tokens
        if matched and not full_phrase_already_present:
            expansions.append(phrase)
            seen.add(phrase)

        if len(expansions) >= _MAX_EXPANSIONS:
            break

    if expansions:
        log_event(logger, logging.INFO, "query_expanded", original=query, expansions=expansions)
    return expansions
