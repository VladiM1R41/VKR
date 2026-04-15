"""Keyword extraction for Layer 2 using YAKE.

YAKE (Yet Another Keyword Extractor) — быстрый unsupervised алгоритм
извлечения ключевых фраз из текста.

Почему YAKE:
- не требует обученной модели или словаря
- работает на CPU за миллисекунды
- достаточно хорош для новостных текстов
- поддерживает русский язык

Принцип: оценивает n-граммы по статистическим признакам:
- caseness (регистр — заглавные слова важнее)
- position (ранние в тексте важнее)
- frequency (частые важнее)
- context (разнообразие контекстов)

Ключевые фразы используются для:
- Qdrant payload (объяснимость: «почему эта статья найдена»)
- автодополнения запросов
- enrichment профилей пользователей
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re


logger = logging.getLogger(__name__)

# Максимум ключевых слов на статью
_MAX_KEYWORDS = 8

# Порог YAKE score (ниже = лучше, YAKE инвертирует)
_YAKE_SCORE_THRESHOLD = 0.15


@dataclass(frozen=True, slots=True)
class KeywordResult:
    """One extracted keyword with its score."""

    text: str
    score: float


@lru_cache(maxsize=1)
def _load_yake():
    """Lazy-load YAKE extractor."""
    try:
        import yake
        return yake.KeywordExtractor(lan="ru", n=3, top=_MAX_KEYWORDS)
    except ImportError:
        logger.warning("yake not installed: keyword extraction disabled")
        return None


def extract_keywords(text: str) -> list[KeywordResult]:
    """Извлечь ключевые фразы из текста через YAKE.

    Args:
        text: Текст статьи (title + content).

    Returns:
        Список KeywordResult, отсортированный по score (лучшие первые).
    """
    extractor = _load_yake()
    if extractor is None:
        return []

    # YAKE требует минимум текста — хотя бы 20 символов
    cleaned = " ".join(text.split())
    if len(cleaned) < 20:
        return []

    try:
        keywords = extractor.extract_keywords(cleaned)
    except Exception as exc:
        logger.warning("YAKE keyword extraction failed: %s", exc)
        return []

    results: list[KeywordResult] = []
    for phrase, score in keywords:
        if score <= _YAKE_SCORE_THRESHOLD:
            # Фильтруем мусорные ключевые слова
            phrase_clean = phrase.strip()
            if phrase_clean and len(phrase_clean) >= 2:
                # Убираем чисто пунктуацию
                if not re.match(r"^[\W_]+$", phrase_clean):
                    results.append(
                        KeywordResult(text=phrase_clean, score=round(score, 4))
                    )

    return results[:_MAX_KEYWORDS]
