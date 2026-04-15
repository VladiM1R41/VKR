"""Lemmatization for Russian text using PyMorphy3.

Лемматизация — приведение слова к словарной форме:
    «ставки» → «ставка», «сказал» → «сказать», «лучший» → «лучший»

Важно для IR: один термин «ставка» должен находить все словоформы
«ставки», «ставке», «ставкой» и т.д. (6 падежей × 2 числа = до 12 форм).

По данным CLEF, лемматизация улучшает качество поиска до 30% для языков
с богатой морфологией (русский, финский, чешский).
"""

from __future__ import annotations

from functools import lru_cache
import logging
import re


logger = logging.getLogger(__name__)
_DEPENDENCY_WARNING_EMITTED = False


@lru_cache(maxsize=1)
def _load_morph() -> object | None:
    """Lazy-load PyMorphy3 morphological analyzer.

    Первый вызов инициализирует словарь (загрузка ~15 MB в память).
    Последующие вызовы используют закэшированный экземпляр.
    """
    global _DEPENDENCY_WARNING_EMITTED
    try:
        import pymorphy3
        return pymorphy3.MorphAnalyzer()
    except ImportError:
        if not _DEPENDENCY_WARNING_EMITTED:
            _DEPENDENCY_WARNING_EMITTED = True
            logger.warning(
                "pymorphy3 not installed: lemmatization will fall back to passthrough. "
                "Install with: pip install pymorphy3"
            )
        return None


def normalize_yo(text: str) -> str:
    """Нормализация буквы Ё → Е для IR-индекса.

    Многие русские источники непоследовательны: «ещё» / «еще», «всё» / «все».
    Для BM25-индекса это два разных термина — ломаем эту проблему заменой.

    НЕ применяется к оригинальному тексту (до лемматизации),
    потому что регистр и Ё важны для NER.
    """
    return text.replace("ё", "е").replace("Ё", "Е")


def lemmatize_text(text: str) -> str:
    """Лемматизировать весь текст.

    Алгоритм:
    1. Заменить ё → е (для единообразия)
    2. Разбить на токены (Razdel)
    3. Каждый токен лемматизировать (PyMorphy3)
    4. Склеить обратно пробелами

    Знаки препинания сохраняются как отдельные токены — они будут
    отфильтрованы на уровне BM25 (idf ≈ 0).

    Args:
        text: Исходный текст (сохраняет регистр до ё→е).

    Returns:
        Лемматизированный текст (нижний регистр).
    """
    morph = _load_morph()
    if morph is None:
        # Fallback: просто lower + ё→е без лемматизации
        return normalize_yo(text).lower()

    from razdel import tokenize

    # Шаг 1: ё → е
    cleaned = normalize_yo(text)

    # Шаг 2: токенизация
    tokens = tokenize(cleaned)

    # Шаг 3: лемматизация каждого токена
    lemmas: list[str] = []
    for token in tokens:
        word = token.text
        # PyMorphy3 работает лучше с lowercase
        parsed = morph.parse(word.lower())
        if parsed:
            # Берём первую (наиболее вероятную) лемму + нормализуем ё→е
            lemma = normalize_yo(parsed[0].normal_form)
            lemmas.append(lemma)
        else:
            # Неизвестное слово /标点 — сохраняем как есть (lowercase)
            lemmas.append(normalize_yo(word.lower()))

    # Шаг 4: склеить
    return " ".join(lemmas)


def extract_unigrams(text: str) -> list[str]:
    """Извлечь унисграммы (отдельные леммы) из текста.

    Удобно для обновления term_vocabulary.
    """
    lemma_text = lemmatize_text(text)
    # Фильтруем короткие токены (< 2 символов) и чисто пунктуацию
    return [
        token for token in lemma_text.split()
        if len(token) >= 2 and not re.match(r"^[\W_]+$", token)
    ]


def extract_bigrams(text: str) -> list[tuple[str, str]]:
    """Извлечь биграммы лемм из текста.

    Удобно для обновления collocations (PMI, χ²).
    Не пересекает границы предложений.
    """
    from jarvis.processing.ir.tokenize import split_sentences

    bigrams: list[tuple[str, str]] = []
    for sentence in split_sentences(text):
        unigrams = extract_unigrams(sentence)
        for i in range(len(unigrams) - 1):
            bigrams.append((unigrams[i], unigrams[i + 1]))
    return bigrams
