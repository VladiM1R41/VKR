"""Corpus vocabulary and collocations batch tasks for Layer 2.

Эти задачи НЕ блокируют online-path (processed=true).
Они запускаются периодически (Celery Beat) и обновляют:

1. term_vocabulary — глобальный словарь терминов с частотами
   (для автокоррекции запросов, autocomplete, аналитики Ципфа/Хипса)

2. collocations — устойчивые словосочетания с PMI-скором
   (для query expansion, объяснимости поиска)

По FINAL_LAYER_2_GUIDE.md разделы 11.6 и 17.5-17.6:
- term_vocabulary обновляется инкрементально по batch или nightly
- collocations — отдельная аналитическая задача, не blocking-step
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from math import log

from sqlalchemy import select, update

from jarvis.core.logging import log_event
from jarvis.db.models import Chunk, Collocation, News, TermVocabulary
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.ir.lemmatize import extract_bigrams, extract_unigrams


logger = logging.getLogger(__name__)

# Минимальная частота термина для включения в словарь
_MIN_TERM_FREQUENCY = 3

# Минимальный PMI для коллокации (сильная ассоциация)
_MIN_PMI_SCORE = 3.0

# Минимальная частота биграммы для рассмотрения
_MIN_BIGRAM_FREQUENCY = 5


@dataclass
class VocabularyUpdateResult:
    """Результат обновления словаря."""

    terms_added: int = 0
    terms_updated: int = 0
    total_terms: int = 0
    elapsed_seconds: float = 0.0


@dataclass
class CollocationUpdateResult:
    """Результат обновления коллокаций."""

    collocations_added: int = 0
    collocations_updated: int = 0
    total_collocations: int = 0
    elapsed_seconds: float = 0.0


def _collect_corpus_lemmas() -> tuple[list[str], list[tuple[str, str]]]:
    """Собрать все леммы и биграммы из обработанных статей.

    lemma_text не хранится в Chunk (только в Qdrant payload),
    поэтому берём news.content и лемматизируем заново.

    Returns:
        (all_unigrams, all_bigrams) — списки для подсчёта частот.
    """
    from jarvis.processing.ir.lemmatize import extract_bigrams, extract_unigrams

    all_unigrams: list[str] = []
    all_bigrams: list[tuple[str, str]] = []

    with SyncSessionLocal() as session:
        # Берём последние обработанные статьи
        news_items = session.scalars(
            select(News).where(News.processed.is_(True))
            .order_by(News.ingested_at.desc())
            .limit(500)  # MVP: последние 500 статей
        ).all()

        for news in news_items:
            text = news.content or ""
            if not text:
                text = news.snippet_lead or ""
            if not text:
                continue

            # extract_unigrams/bigrams уже лемматизируют внутри
            all_unigrams.extend(extract_unigrams(text))
            all_bigrams.extend(extract_bigrams(text))

    return all_unigrams, all_bigrams


def update_term_vocabulary() -> VocabularyUpdateResult:
    """Обновить term_vocabulary из корпуса.

    Алгоритм:
    1. Собрать все унисграммы из чанков
    2. Подсчитать doc_frequency (в скольких документах) и collection_frequency
    3. Upsert в БД

    Вызывается периодически (Celery Beat), не блокирует processed=true.
    """
    import time
    t0 = time.time()

    all_unigrams, _ = _collect_corpus_lemmas()
    if not all_unigrams:
        return VocabularyUpdateResult()

    # Считаем частоты
    collection_counter = Counter(all_unigrams)

    # doc_frequency: упрощённо = collection_frequency для MVP
    # (в полной версии — считать в скольких разных документах)
    doc_counter = collection_counter

    result = VocabularyUpdateResult(elapsed_seconds=0.0)

    with SyncSessionLocal() as session:
        for term, coll_freq in collection_counter.items():
            if coll_freq < _MIN_TERM_FREQUENCY:
                continue

            existing = session.get(TermVocabulary, term)
            if existing:
                existing.doc_frequency = doc_counter.get(term, 0)
                existing.collection_frequency = coll_freq
                existing.updated_at = datetime.now(timezone.utc)
                result.terms_updated += 1
            else:
                session.add(
                    TermVocabulary(
                        term=term,
                        doc_frequency=doc_counter.get(term, 0),
                        collection_frequency=coll_freq,
                    )
                )
                result.terms_added += 1

        session.commit()

    # Итого
    with SyncSessionLocal() as session:
        result.total_terms = session.query(TermVocabulary).count()

    result.elapsed_seconds = round(time.time() - t0, 2)

    log_event(
        logger,
        logging.INFO,
        "term_vocabulary_updated",
        terms_added=result.terms_added,
        terms_updated=result.terms_updated,
        total_terms=result.total_terms,
        elapsed_seconds=result.elapsed_seconds,
    )
    return result


def update_collocations() -> CollocationUpdateResult:
    """Обновить collocations из корпуса.

    Алгоритм:
    1. Собрать все биграммы из чанков
    2. Подсчитать частоты биграмм и униграмм
    3. Вычислить PMI: PMI(x,y) = log(P(x,y) / (P(x) * P(y)))
    4. Фильтровать по PMI > threshold и min frequency
    5. Upsert в БД

    PMI > 3.0 означает: биграмма встречается в exp(3) ≈ 20 раз чаще
    чем ожидалось бы случайно — сильная ассоциация.

    Вызывается периодически (Celery Beat), не блокирует processed=true.
    """
    import time
    t0 = time.time()

    _, all_bigrams = _collect_corpus_lemmas()
    if not all_bigrams:
        return CollocationUpdateResult()

    # Считаем частоты биграмм
    bigram_counter = Counter(all_bigrams)

    # Считаем частоты униграмм (для PMI)
    unigram_counter: Counter = Counter()
    for a, b in all_bigrams:
        unigram_counter[a] += 1
        unigram_counter[b] += 1

    total_bigrams = sum(bigram_counter.values())
    total_unigrams = sum(unigram_counter.values())

    result = CollocationUpdateResult(elapsed_seconds=0.0)

    with SyncSessionLocal() as session:
        for (term_a, term_b), freq in bigram_counter.items():
            if freq < _MIN_BIGRAM_FREQUENCY:
                continue

            # PMI = log(P(a,b) / (P(a) * P(b)))
            p_joint = freq / total_bigrams
            p_a = unigram_counter.get(term_a, 0) / total_unigrams
            p_b = unigram_counter.get(term_b, 0) / total_unigrams

            if p_a == 0 or p_b == 0:
                continue

            pmi = log(p_joint / (p_a * p_b))
            if pmi < _MIN_PMI_SCORE:
                continue

            existing = session.get(
                Collocation,
                {"term_a": term_a, "term_b": term_b},
            )
            if existing:
                existing.pmi_score = round(pmi, 4)
                existing.frequency = freq
                existing.updated_at = datetime.now(timezone.utc)
                result.collocations_updated += 1
            else:
                session.add(
                    Collocation(
                        term_a=term_a,
                        term_b=term_b,
                        pmi_score=round(pmi, 4),
                        frequency=freq,
                    )
                )
                result.collocations_added += 1

        session.commit()

    # Итого
    with SyncSessionLocal() as session:
        result.total_collocations = session.query(Collocation).count()

    result.elapsed_seconds = round(time.time() - t0, 2)

    log_event(
        logger,
        logging.INFO,
        "collocations_updated",
        collocations_added=result.collocations_added,
        collocations_updated=result.collocations_updated,
        total_collocations=result.total_collocations,
        elapsed_seconds=result.elapsed_seconds,
    )
    return result
