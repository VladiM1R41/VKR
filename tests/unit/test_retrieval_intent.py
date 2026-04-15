"""Tests for Layer 3 intent classification."""

import pytest

from jarvis.retrieval.services.intent_classifier import classify_intent, IntentResult


class TestIntentClassification:
    """Тесты rule-based классификации intent."""

    def test_factual_default(self):
        """По умолчанию — FACTUAL."""
        result = classify_intent("новости за сегодня")
        assert result.intent == "FACTUAL"

    def test_factual_what_happened(self):
        """Вопрос о событиях → FACTUAL."""
        result = classify_intent("Что произошло с ЦБ?")
        assert result.intent == "FACTUAL"

    def test_capability_why(self):
        """«Почему» → CAPABILITY."""
        result = classify_intent("Почему выросла инфляция?")
        assert result.intent == "CAPABILITY"

    def test_capability_what_means(self):
        """«Что означает» → CAPABILITY."""
        result = classify_intent("Что означает повышение ставки?")
        assert result.intent == "CAPABILITY"

    def test_intent_forecast(self):
        """«Прогноз» → INTENT."""
        result = classify_intent("Какой прогноз по рублю?")
        assert result.intent == "INTENT"

    def test_intent_what_will(self):
        """«Что будет» → INTENT."""
        result = classify_intent("Что будет с акциями?")
        assert result.intent == "INTENT"

    def test_empty_query(self):
        """Пустой запрос → FACTUAL."""
        result = classify_intent("")
        assert result.intent == "FACTUAL"

    def test_confidence_scales_with_matches(self):
        """Уверенность растёт с числом совпадений."""
        r1 = classify_intent("прогноз")  # 1 совпадение
        r2 = classify_intent("прогноз что будет с акциями")  # 2+ совпадений
        assert r2.confidence >= r1.confidence

    def test_method_is_rule_based(self):
        """Метод всегда rule-based в MVP."""
        result = classify_intent("тест")
        assert result.method == "rule-based"

    def test_result_is_dataclass(self):
        """Результат — IntentResult dataclass."""
        result = classify_intent("тест")
        assert isinstance(result, IntentResult)
        assert hasattr(result, "intent")
        assert hasattr(result, "confidence")
        assert hasattr(result, "method")
