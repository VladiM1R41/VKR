"""Conservative query autocorrect for Layer 3.

The vocabulary is built from Layer 2 lemmas, so we must not replace valid
Russian surface forms with their lemmas. Lemmas are used to decide whether a
word is known; corrections are applied only to likely typos.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re
import time

from jarvis.core.logging import log_event
from jarvis.db.models import TermVocabulary
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.ir.lemmatize import lemmatize_text
from jarvis.processing.ir.quality_terms import is_informative_term


logger = logging.getLogger(__name__)

_K = 3
_JACCARD_THRESHOLD = 0.5
_MAX_CANDIDATES = 5
_MIN_TERM_LENGTH = 3
_VOCABULARY_TTL_SECONDS = 15 * 60
_TOKEN_RE = re.compile(r"^[A-Za-zА-Яа-яЁё-]+$")

_vocabulary_cache: dict[str, object] = {
    "loaded_at": 0.0,
    "value": {},
}


@dataclass(frozen=True, slots=True)
class AutocorrectResult:
    """Autocorrection result."""

    original: str
    corrected: str
    was_corrected: bool


def _trigrams(word: str) -> set[str]:
    """Extract k-grams from a word with padding."""
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


def clear_vocabulary_cache() -> None:
    """Clear cached Layer 2 vocabulary after analytics refresh or in tests."""
    _vocabulary_cache["loaded_at"] = 0.0
    _vocabulary_cache["value"] = {}


def _load_vocabulary() -> dict[str, int]:
    """Load term vocabulary from PostgreSQL with a short TTL."""
    now = time.monotonic()
    cached = _vocabulary_cache.get("value")
    loaded_at = float(_vocabulary_cache.get("loaded_at") or 0.0)
    if isinstance(cached, dict) and cached and now - loaded_at < _VOCABULARY_TTL_SECONDS:
        return cached

    with SyncSessionLocal() as session:
        rows = session.query(TermVocabulary.term, TermVocabulary.doc_frequency).all()
        vocabulary = {
            term.lower(): int(df)
            for term, df in rows
            if term and df > 0 and len(term) >= _MIN_TERM_LENGTH and is_informative_term(term)
        }
    _vocabulary_cache["loaded_at"] = now
    _vocabulary_cache["value"] = vocabulary
    return vocabulary


def _find_candidates(word: str, vocabulary: dict[str, int]) -> list[tuple[str, int]]:
    """Find candidate corrections for a misspelled word."""
    word_lower = word.lower()
    word_trigrams = _trigrams(word_lower)
    candidates: list[tuple[str, float, int]] = []

    for term in vocabulary:
        jaccard = _jaccard(word_trigrams, _trigrams(term))
        if jaccard >= _JACCARD_THRESHOLD:
            lev = _levenshtein(word_lower, term)
            candidates.append((term, jaccard, lev))

    candidates.sort(key=lambda x: (x[2], -vocabulary.get(x[0], 0)))
    return [(term, lev) for term, _, lev in candidates[:_MAX_CANDIDATES]]


def _is_known_surface_or_lemma(word: str, vocabulary: dict[str, int]) -> bool:
    lower = word.lower()
    if lower in vocabulary:
        return True
    lemma = lemmatize_text(word).strip().lower()
    return bool(lemma and lemma in vocabulary)


def _should_skip_word(word: str) -> bool:
    stripped = word.strip()
    if len(stripped) < _MIN_TERM_LENGTH:
        return True
    if not _TOKEN_RE.match(stripped):
        return True
    if not is_informative_term(stripped):
        return True
    if stripped.isupper():
        return True
    if stripped[:1].isupper():
        # Conservative guard for person/location names.
        return True
    return False


def autocorrect_query(query: str) -> AutocorrectResult:
    """Autocorrect likely typos without normalizing valid words to lemmas."""
    vocabulary = _load_vocabulary()
    words = query.strip().split()
    if not words:
        return AutocorrectResult(original=query, corrected=query, was_corrected=False)

    corrected_words: list[str] = []
    was_corrected = False

    for word in words:
        if _should_skip_word(word) or _is_known_surface_or_lemma(word, vocabulary):
            corrected_words.append(word)
            continue

        candidates = _find_candidates(word, vocabulary)
        if candidates and candidates[0][1] <= 2:
            corrected, distance = candidates[0]
            corrected_words.append(corrected)
            was_corrected = True
            log_event(
                logger,
                logging.INFO,
                "autocorrect_applied",
                original=word,
                corrected=corrected,
                distance=distance,
            )
        else:
            corrected_words.append(word)

    corrected_query = " ".join(corrected_words)
    if was_corrected:
        log_event(logger, logging.INFO, "query_autocorrected", original=query, corrected=corrected_query)

    return AutocorrectResult(
        original=query,
        corrected=corrected_query,
        was_corrected=was_corrected,
    )
