"""Corpus vocabulary and collocations batch tasks for Layer 2."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from math import log

from sqlalchemy import select

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings
from jarvis.db.models import Collocation, News, TermVocabulary
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.ir.lemmatize import extract_bigrams, extract_unigrams
from jarvis.processing.ir.quality_terms import is_informative_bigram, is_informative_term


logger = logging.getLogger(__name__)

_MIN_TERM_FREQUENCY = 3
_MIN_PMI_SCORE = 3.0
_MIN_BIGRAM_FREQUENCY = 5


@dataclass
class VocabularyUpdateResult:
    """Result of vocabulary rebuild."""

    terms_added: int = 0
    terms_updated: int = 0
    total_terms: int = 0
    elapsed_seconds: float = 0.0


@dataclass
class CollocationUpdateResult:
    """Result of collocation rebuild."""

    collocations_added: int = 0
    collocations_updated: int = 0
    total_collocations: int = 0
    elapsed_seconds: float = 0.0


def _collect_processed_texts() -> list[str]:
    """Collect processed article texts for corpus-level analytics.

    PROCESSING_ANALYTICS_MAX_ARTICLES=0 means the full processed corpus.
    """

    settings = get_settings()
    with SyncSessionLocal() as session:
        stmt = select(News).where(News.processed.is_(True)).order_by(News.ingested_at.desc())
        if settings.processing_analytics_max_articles > 0:
            stmt = stmt.limit(settings.processing_analytics_max_articles)
        news_items = session.scalars(stmt).all()

    texts: list[str] = []
    for news in news_items:
        text = news.content or news.snippet_lead or ""
        if text.strip():
            texts.append(text)
    return texts


def _filter_unigrams(terms: list[str]) -> list[str]:
    """Keep only terms useful for corpus vocabulary analytics."""

    return [term for term in terms if is_informative_term(term)]


def _filter_bigrams(bigrams: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Keep only bigrams useful for query expansion and corpus analytics."""

    return [(a, b) for a, b in bigrams if is_informative_bigram(a, b)]


def _collect_corpus_lemmas() -> tuple[list[str], list[tuple[str, str]]]:
    """Collect all unigrams and bigrams from the configured processed corpus window."""

    all_unigrams: list[str] = []
    all_bigrams: list[tuple[str, str]] = []
    for text in _collect_processed_texts():
        all_unigrams.extend(_filter_unigrams(extract_unigrams(text)))
        all_bigrams.extend(_filter_bigrams(extract_bigrams(text)))
    return all_unigrams, all_bigrams


def _count_term_frequencies(documents: list[list[str]]) -> tuple[Counter[str], Counter[str]]:
    """Return exact doc_frequency and collection_frequency counters."""

    doc_counter: Counter[str] = Counter()
    collection_counter: Counter[str] = Counter()
    for terms in documents:
        collection_counter.update(terms)
        doc_counter.update(set(terms))
    return doc_counter, collection_counter


def update_term_vocabulary() -> VocabularyUpdateResult:
    """Rebuild term_vocabulary from the configured processed corpus window."""

    import time

    t0 = time.time()
    documents = [_filter_unigrams(extract_unigrams(text)) for text in _collect_processed_texts()]
    documents = [terms for terms in documents if terms]
    if not documents:
        return VocabularyUpdateResult()

    doc_counter, collection_counter = _count_term_frequencies(documents)
    result = VocabularyUpdateResult(elapsed_seconds=0.0)
    eligible_terms = [
        (term, coll_freq)
        for term, coll_freq in collection_counter.items()
        if coll_freq >= _MIN_TERM_FREQUENCY and is_informative_term(term)
    ]

    with SyncSessionLocal() as session:
        session.query(TermVocabulary).delete(synchronize_session=False)
        for term, coll_freq in eligible_terms:
            session.add(
                TermVocabulary(
                    term=term,
                    doc_frequency=doc_counter.get(term, 0),
                    collection_frequency=coll_freq,
                )
            )
            result.terms_added += 1

        session.commit()

    with SyncSessionLocal() as session:
        result.total_terms = session.query(TermVocabulary).count()

    result.elapsed_seconds = round(time.time() - t0, 2)
    log_event(
        logger,
        logging.INFO,
        "term_vocabulary_updated",
        corpus_documents=len(documents),
        terms_added=result.terms_added,
        terms_updated=result.terms_updated,
        total_terms=result.total_terms,
        elapsed_seconds=result.elapsed_seconds,
    )
    return result


def update_collocations() -> CollocationUpdateResult:
    """Rebuild collocations from the configured processed corpus window."""

    import time

    t0 = time.time()
    all_unigrams, all_bigrams = _collect_corpus_lemmas()
    if not all_bigrams:
        return CollocationUpdateResult()

    bigram_counter = Counter(all_bigrams)
    unigram_counter: Counter[str] = Counter(all_unigrams)

    total_bigrams = sum(bigram_counter.values())
    total_unigrams = sum(unigram_counter.values())
    result = CollocationUpdateResult(elapsed_seconds=0.0)
    eligible_collocations: list[tuple[str, str, float, int]] = []

    for (term_a, term_b), freq in bigram_counter.items():
        if freq < _MIN_BIGRAM_FREQUENCY or not is_informative_bigram(term_a, term_b):
            continue

        p_joint = freq / total_bigrams
        p_a = unigram_counter.get(term_a, 0) / total_unigrams
        p_b = unigram_counter.get(term_b, 0) / total_unigrams
        if p_a == 0 or p_b == 0:
            continue

        pmi = log(p_joint / (p_a * p_b))
        if pmi < _MIN_PMI_SCORE:
            continue

        eligible_collocations.append((term_a, term_b, round(pmi, 4), freq))

    with SyncSessionLocal() as session:
        session.query(Collocation).delete(synchronize_session=False)
        for term_a, term_b, pmi, freq in eligible_collocations:
            session.add(
                Collocation(
                    term_a=term_a,
                    term_b=term_b,
                    pmi_score=pmi,
                    frequency=freq,
                )
            )
            result.collocations_added += 1

        session.commit()

    with SyncSessionLocal() as session:
        result.total_collocations = session.query(Collocation).count()

    result.elapsed_seconds = round(time.time() - t0, 2)
    log_event(
        logger,
        logging.INFO,
        "collocations_updated",
        corpus_unigrams=len(all_unigrams),
        corpus_bigrams=len(all_bigrams),
        collocations_added=result.collocations_added,
        collocations_updated=result.collocations_updated,
        total_collocations=result.total_collocations,
        elapsed_seconds=result.elapsed_seconds,
    )
    return result
