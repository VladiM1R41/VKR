"""Query autocorrect for Layer 3 — «Вы имели в виду...?»

Uses k-gram index (k=3) + Jaccard coefficient + Levenshtein distance
to find corrections for misspelled query words.

Based on Manning, ch. 3: spelling correction.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
import logging
from typing import Optional

from jarvis.core.logging import log_event
from jarvis.db.models import TermVocabulary
from jarvis.db.session import SyncSessionLocal


logger = logging.getLogger(__name__)

_K = 3  # k-gram size
_JACCARD_THRESHOLD = 0.5  # minimum Jaccard coefficient (raised from 0.4)
_MAX_CANDIDATES = 5  # max candidates per word
_MIN_TERM_LENGTH = 3  # ignore terms shorter than this


@dataclass(frozen=True, slots=True)
class AutocorrectResult:
    """Autocorrection result."""

    original: str
    corrected: str
    was_corrected: bool


def _trigrams(word: str) -> set[str]:
    """Extract k-grams (k=3) from a word with padding."""
    padded = f"^{word}$"
    return {padded[i:i + _K] for i in range(len(padded) - _K + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard coefficient between two sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


@lru_cache(maxsize=4096)
def _levenshtein(s1: str, s2: str) -> int:
    """Levenshtein distance with caching."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


@lru_cache(maxsize=1)
def _load_vocabulary() -> dict[str, int]:
    """Load term vocabulary from PostgreSQL with document frequencies.

    Filters out terms shorter than _MIN_TERM_LENGTH to avoid
    spurious corrections with short lemmas like 'ст', 'в', 'к'.

    Returns dict: {term: doc_frequency}.
    Cached for performance.
    """
    with SyncSessionLocal() as session:
        rows = session.query(TermVocabulary.term, TermVocabulary.doc_frequency).all()
        return {
            term: df for term, df in rows
            if df > 0 and len(term) >= _MIN_TERM_LENGTH
        }


def _find_candidates(word: str, vocabulary: dict[str, int]) -> list[tuple[str, int]]:
    """Find candidate corrections for a misspelled word.

    Algorithm (Manning, ch. 3):
    1. Extract trigrams from word
    2. Find vocabulary terms sharing trigrams
    3. Filter by Jaccard coefficient
    4. Rank by Levenshtein distance
    5. Break ties by document frequency (more common = better)

    Args:
        word: Misspelled word.
        vocabulary: {term: doc_frequency} dict.

    Returns:
        List of (candidate, levenshtein_distance) sorted by quality.
    """
    word_trigrams = _trigrams(word)

    # Find candidates sharing trigrams
    candidates: list[tuple[str, float, int]] = []  # (term, jaccard, lev)

    for term in vocabulary:
        term_trigrams = _trigrams(term)
        jaccard = _jaccard(word_trigrams, term_trigrams)

        if jaccard >= _JACCARD_THRESHOLD:
            lev = _levenshtein(word.lower(), term.lower())
            candidates.append((term, jaccard, lev))

    # Sort: lowest Levenshtein first, then highest doc_frequency for ties
    candidates.sort(key=lambda x: (x[2], -vocabulary.get(x[0], 0)))

    return [(term, lev) for term, _, lev in candidates[:_MAX_CANDIDATES]]


def autocorrect_query(query: str) -> AutocorrectResult:
    """Autocorrect a search query.

    For each word not in vocabulary, find the best candidate correction.
    Prefer corrections with Levenshtein distance = 1, then 2.

    Args:
        query: Raw user query.

    Returns:
        AutocorrectResult with original and corrected query.
    """
    vocabulary = _load_vocabulary()
    words = query.strip().split()
    if not words:
        return AutocorrectResult(original=query, corrected=query, was_corrected=False)

    corrected_words: list[str] = []
    was_corrected = False

    for word in words:
        # Check if word is in vocabulary (case-insensitive)
        if word.lower() in {v.lower() for v in vocabulary}:
            corrected_words.append(word)
            continue

        # Find candidates
        candidates = _find_candidates(word, vocabulary)
        if candidates:
            best = candidates[0]  # best candidate (lowest Levenshtein)
            if best[1] <= 2:  # max distance 2
                corrected_words.append(best[0])
                was_corrected = True
                log_event(
                    logger,
                    logging.INFO,
                    "autocorrect_applied",
                    original=word,
                    corrected=best[0],
                    distance=best[1],
                )
            else:
                corrected_words.append(word)
        else:
            corrected_words.append(word)

    corrected = " ".join(corrected_words)

    if was_corrected:
        log_event(
            logger,
            logging.INFO,
            "query_autocorrected",
            original=query,
            corrected=corrected,
        )

    return AutocorrectResult(
        original=query,
        corrected=corrected,
        was_corrected=was_corrected,
    )
