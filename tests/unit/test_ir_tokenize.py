"""Tests for Layer 2 IR tokenization (Razdel)."""

import pytest

from jarvis.processing.ir.tokenize import split_sentences, tokenize_cached


class TestTokenize:
    """Тесты токенизации русского текста."""

    def test_tokenize_simple(self):
        tokens = tokenize_cached("ЦБ повысил ставку")
        assert tokens == ["ЦБ", "повысил", "ставку"]

    def test_tokenize_punctuation(self):
        tokens = tokenize_cached("Он сказал: «Привет»!")
        # Razdel разделяет пунктуацию как отдельные токены
        assert "Привет" in tokens
        assert ":" in tokens

    def test_tokenize_cached_result(self):
        """Кэш должен возвращать одинаковый результат."""
        r1 = tokenize_cached("тест")
        r2 = tokenize_cached("тест")
        assert r1 == r2


class TestSplitSentences:
    """Тесты сегментации на предложения."""

    def test_single_sentence(self):
        sentences = split_sentences("ЦБ повысил ставку.")
        assert len(sentences) == 1
        assert sentences[0] == "ЦБ повысил ставку."

    def test_multiple_sentences(self):
        sentences = split_sentences("ЦБ повысил ставку. Инфляция растёт. Это плохо.")
        assert len(sentences) == 3

    def test_abbreviations(self):
        """Аббревиатуры не должны ломать сегментацию."""
        text = "ЦБ РФ принял решение. Это важно для экономики."
        sentences = split_sentences(text)
        # Должно быть 2 предложения, а не 3 (из-за "РФ.")
        assert len(sentences) == 2

    def test_empty_text(self):
        sentences = split_sentences("")
        assert sentences == []

    def test_whitespace_only(self):
        sentences = split_sentences("   \n\n   ")
        assert sentences == []
