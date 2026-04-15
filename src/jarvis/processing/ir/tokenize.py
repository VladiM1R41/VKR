"""Tokenization helpers for Russian text using Razdel."""

from __future__ import annotations

from functools import lru_cache


def _tokenize_sentence(text: str) -> list[str]:
    """Tokenize a single sentence into word tokens.

    Использует Razdel — библиотеку для сегментации русского текста.
    Возвращает список токенов (слов, знаков препинания как отдельных токенов).
    """
    from razdel import tokenize

    return [token.text for token in tokenize(text)]


def split_sentences(text: str) -> list[str]:
    """Разбить текст на предложения.

    Использует Razdel sentenize для корректной сегментации русского текста.
    Учитывает сокращения, аббревиатуры, многоточия.

    Args:
        text: Исходный текст.

    Returns:
        Список предложений (без лишних пробелов).
    """
    from razdel import sentenize

    sentences = sentenize(text)
    result = []
    for sentence in sentences:
        s = text[sentence.start:sentence.stop].strip()
        if s:
            result.append(s)
    return result


@lru_cache(maxsize=4096)
def tokenize_cached(text: str) -> list[str]:
    """Tokenize text with simple caching for repeated inputs.

    Кэш ускоряет обработку одинаковых заголовков и частых фраз.
    """
    return _tokenize_sentence(text)
