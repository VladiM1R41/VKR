"""Tests for Layer 3 caching service."""

import pytest

from jarvis.retrieval.services.cache import SearchCache


class TestSearchCache:
    """Тесты кэша поиска."""

    def test_init(self):
        cache = SearchCache()
        assert cache is not None

    def test_cache_key_deterministic(self):
        """Один и тот же запрос → один и тот же ключ."""
        cache = SearchCache()
        key1 = cache._cache_key("ставка ЦБ", "")
        key2 = cache._cache_key("ставка ЦБ", "")
        assert key1 == key2

    def test_cache_key_case_insensitive(self):
        """Регистр не должен влиять на ключ."""
        cache = SearchCache()
        key1 = cache._cache_key("ставка ЦБ", "")
        key2 = cache._cache_key("СТАВКА цб", "")
        # Нормализация делает lowercase
        assert key1 == key2

    def test_cache_key_different_queries(self):
        """Разные запросы → разные ключи."""
        cache = SearchCache()
        key1 = cache._cache_key("ставка", "")
        key2 = cache._cache_key("инфляция", "")
        assert key1 != key2

    def test_cache_key_with_filters(self):
        """Фильтры должны влиять на ключ."""
        cache = SearchCache()
        key1 = cache._cache_key("ставка", "source=1")
        key2 = cache._cache_key("ставка", "source=2")
        assert key1 != key2

    def test_cache_key_strips_whitespace(self):
        """Лишние пробелы не должны влиять."""
        cache = SearchCache()
        key1 = cache._cache_key("  ставка  ", "")
        key2 = cache._cache_key("ставка", "")
        assert key1 == key2
