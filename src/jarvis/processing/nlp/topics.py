"""Zero-shot topic classification fallback for Layer 2.

Когда у статьи НЕТ категорий из источника (news.extra.categories пуст或缺失),
используем zero-shot классификацию через NLI-модель.

Принцип: задаём список候选 тем текстом («Экономика», «Политика»...),
модель оценивает NLI (Natural Language Inference) — насколько текст
«подтверждает» каждую тему.

Используем rubert-base-cased-nli — русскую NLI-модель из HuggingFace.
Не требует обученного классификатора или размеченного корпуса.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from jarvis.processing.services.topic_mapping import TopicMatch


logger = logging.getLogger(__name__)

# Кандидатные темы для zero-shot классификации
# Тот же список, что в _TOPIC_RULES (topic_mapping.py)
_ZERO_SHOT_CANDIDATES = [
    "Экономика",
    "Политика",
    "Международные отношения",
    "Финансы",
    "Технологии",
    "Бизнес",
    "Общество",
    "Безопасность",
    "Энергетика",
    "Транспорт",
    "Право",
    "Наука",
]

# Порог уверенности: темы ниже этого confidence не включаем
_ZERO_SHOT_THRESHOLD = 0.35

# Максимум тем на статью
_MAX_TOPICS = 3


@lru_cache(maxsize=1)
def _load_zero_shot_model():
    """Lazy-load NLI модели для zero-shot классификации.

    Первый вызов скачивает модель (~1.2 GB) с HuggingFace.
    Последующие вызовы используют закэшированную модель.
    """
    from transformers import pipeline

    # rubert-base-cased-nli — русская NLI модель
    # Альтернатива: snli-base, но она хуже для русского
    try:
        classifier = pipeline(
            "zero-shot-classification",
            model="cointegrated/rubert-base-cased-nli-threeway",
            device=-1,  # CPU; для GPU поставить 0
        )
        return classifier
    except Exception as exc:
        logger.warning("zero-shot classifier unavailable: %s", exc)
        return None


def classify_topics_zero_shot(text: str, max_length: int = 512) -> list[TopicMatch]:
    """Классифицировать текст по темам через zero-shot NLI.

    Args:
        text: Текст статьи (title + первые ~200 слов body).
        max_length: Максимальная длина текста для модели.

    Returns:
        Список TopicMatch с confidence scores, отсортированный по убыванию.
    """
    classifier = _load_zero_shot_model()
    if classifier is None:
        return []

    # Обрезаем текст чтобы не превышать контекстное окно
    truncated = text[:max_length * 4]  # ~4 символа на токен

    try:
        result = classifier(
            truncated,
            candidate_labels=_ZERO_SHOT_CANDIDATES,
            multi_label=True,  # статья может быть про несколько тем
        )
    except Exception as exc:
        logger.warning("zero-shot classification failed: %s", exc)
        return []

    matches: list[TopicMatch] = []
    for label, score in zip(result["labels"], result["scores"], strict=True):
        if score >= _ZERO_SHOT_THRESHOLD:
            matches.append(TopicMatch(name=label, confidence=round(score, 4)))

    # Сортируем по уверенности и берём топ-3
    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches[:_MAX_TOPICS]
