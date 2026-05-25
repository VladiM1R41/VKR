"""Regression tests for Layer 3 production hardening."""

from __future__ import annotations

from datetime import datetime, timezone

from jarvis.processing.services.embedding_runtime import EmbeddingOutput
from jarvis.retrieval.models.search_models import SearchRequest
from jarvis.retrieval.services.intent_classifier import IntentResult
from jarvis.retrieval.services.qdrant_search import SearchResult
from jarvis.retrieval.services.query_autocorrect import autocorrect_query
from jarvis.retrieval.services.query_expansion import expand_query_with_collocations
from jarvis.retrieval.services.query_preprocessing import QueryContext
from jarvis.retrieval.services.rate_limiter import RateLimiter
from jarvis.retrieval.services.reranking import RerankedResult
from jarvis.retrieval.services.search_service import SearchService


def _patch_query_steps(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service.autocorrect_query",
        lambda query: type("AC", (), {"corrected": query, "was_corrected": False})(),
    )
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service.preprocess_query",
        lambda query: QueryContext(
            original=query,
            lemma=query.lower(),
            intent=IntentResult(intent="FACTUAL", confidence=0.9, method="rule-based"),
            dense_vector=[0.1, 0.2],
            sparse_indices=[7],
            sparse_values=[0.8],
        ),
    )
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service.expand_query_with_collocations",
        lambda lemma: [],
    )
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service._build_additional_query_vectors",
        lambda expansions: [],
    )


class _FakeLogger:
    def __init__(self):
        self.calls = []

    def log_search(self, **kwargs):
        self.calls.append(kwargs)


class _FakeCache:
    def __init__(self, cached=None):
        self.cached = cached
        self.set_calls = []

    def get(self, query, filters_hash=""):
        return self.cached

    def set(self, query, filters_hash, result, information_type="daily"):
        self.set_calls.append((query, filters_hash, result, information_type))


def test_cache_hit_is_logged(monkeypatch) -> None:
    service = SearchService()
    service._cache = _FakeCache(
        cached={
            "query": "ставка цб",
            "corrected_query": None,
            "intent": "FACTUAL",
            "results": [
                {
                    "chunk_id": "chunk-1",
                    "news_id": 10,
                    "source_id": 1,
                    "source_name": "RBC",
                    "title": "Ставка ЦБ",
                    "snippet": "Ставка ЦБ сохранена.",
                    "score": 0.9,
                    "rerank_score": 0.8,
                    "retrieval_score": 0.7,
                    "retrieval_mode": "qdrant_hybrid",
                    "topics": ["economy"],
                    "entities": ["Банк России"],
                    "keywords": ["ставка"],
                    "published_at": None,
                    "explanation": "cached",
                }
            ],
            "total": 1,
            "search_time_ms": 12.0,
        }
    )
    fake_logger = _FakeLogger()
    service._logger = fake_logger

    response = service.search(SearchRequest(query="ставка цб"))

    assert response.total == 1
    assert response.search_time_ms != 12.0
    assert len(fake_logger.calls) == 1
    assert fake_logger.calls[0]["cache_hit"] is True
    assert fake_logger.calls[0]["retrieval_mode"] == "cache"
    assert fake_logger.calls[0]["result_rows"][0]["score"] == 0.9


def test_search_sorts_by_final_score_after_rerank(monkeypatch) -> None:
    _patch_query_steps(monkeypatch)
    service = SearchService()
    service._cache = _FakeCache()
    service._logger = _FakeLogger()

    class FakeQdrant:
        last_error = None

        def search(self, **kwargs):
            published_at = datetime.now(timezone.utc)
            return [
                SearchResult(
                    point_id="weak",
                    news_id=1,
                    source_id=1,
                    source_name="Weak",
                    title="Weak",
                    text="ставка",
                    score=0.9,
                    zone="body",
                    published_at=published_at,
                    trust_score=0.1,
                    content_grade=6,
                ),
                SearchResult(
                    point_id="strong",
                    news_id=2,
                    source_id=2,
                    source_name="Strong",
                    title="Strong",
                    text="ставка",
                    score=0.8,
                    zone="title",
                    published_at=published_at,
                    trust_score=1.0,
                    content_grade=1,
                ),
            ]

    class FakeReranker:
        def rerank(self, query, candidates):
            return [
                RerankedResult(result=candidates[0], rerank_score=0.95),
                RerankedResult(result=candidates[1], rerank_score=0.80),
            ]

    service._qdrant = FakeQdrant()
    service._reranker = FakeReranker()

    response = service.search(SearchRequest(query="ставка", limit=2))

    assert [item.news_id for item in response.results] == [2, 1]


def test_qdrant_failure_uses_fts_fallback_without_cache(monkeypatch) -> None:
    _patch_query_steps(monkeypatch)
    service = SearchService()
    fake_cache = _FakeCache()
    service._cache = fake_cache
    service._logger = _FakeLogger()

    class FailingQdrant:
        last_error = "boom"

        def search(self, **kwargs):
            return []

    class FakeFTS:
        def search(self, query, **kwargs):
            return [
                SearchResult(
                    point_id="postgres-fts:42",
                    news_id=42,
                    source_id=1,
                    source_name="FTS",
                    title="Fallback",
                    text="fallback text",
                    score=0.5,
                    zone="body",
                    retrieval_mode="postgres_fts_fallback",
                )
            ]

    class FakeReranker:
        def rerank(self, query, candidates):
            return [RerankedResult(result=item, rerank_score=0.5) for item in candidates]

    service._qdrant = FailingQdrant()
    service._postgres_fts = FakeFTS()
    service._reranker = FakeReranker()

    response = service.search(SearchRequest(query="fallback"))

    assert response.results[0].retrieval_mode == "postgres_fts_fallback"
    assert fake_cache.set_calls == []


def test_healthy_qdrant_is_supplemented_by_fts(monkeypatch) -> None:
    _patch_query_steps(monkeypatch)
    service = SearchService()
    service._cache = _FakeCache()
    service._logger = _FakeLogger()

    class FakeQdrant:
        last_error = None

        def search(self, **kwargs):
            return [
                SearchResult(
                    point_id="qdrant:1",
                    news_id=1,
                    source_id=1,
                    source_name="Qdrant",
                    title="Semantic result",
                    text="semantic",
                    score=0.2,
                    zone="body",
                    trust_score=0.5,
                    content_grade=4,
                )
            ]

    class FakeFTS:
        def search(self, query, **kwargs):
            return [
                SearchResult(
                    point_id="postgres-fts:2",
                    news_id=2,
                    source_id=2,
                    source_name="FTS",
                    title="Exact title result",
                    text="exact",
                    score=1.0,
                    zone="title",
                    trust_score=0.9,
                    content_grade=1,
                    retrieval_mode="postgres_fts_fallback",
                )
            ]

    class FakeReranker:
        def rerank(self, query, candidates):
            return [RerankedResult(result=item, rerank_score=0.5) for item in candidates]

    service._qdrant = FakeQdrant()
    service._postgres_fts = FakeFTS()
    service._reranker = FakeReranker()

    response = service.search(SearchRequest(query="exact title", limit=2))

    assert response.results[0].news_id == 2
    assert service._logger.calls[0]["retrieval_mode"] == "qdrant_hybrid+postgres_fts"


def test_autocorrect_does_not_convert_valid_forms_to_lemmas(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_autocorrect._load_vocabulary",
        lambda: {"рассказать": 20, "поиск": 15},
    )

    result = autocorrect_query("рассказал поисках")

    assert result.corrected == "рассказал поисках"
    assert result.was_corrected is False


def test_autocorrect_still_fixes_likely_typo(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_autocorrect._load_vocabulary",
        lambda: {"ставка": 30},
    )

    result = autocorrect_query("ставкка")

    assert result.corrected == "ставка"
    assert result.was_corrected is True


def test_query_expansion_uses_token_matching(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_expansion._load_collocations",
        lambda: [("мировой", "банк", 9.0)],
    )

    assert expand_query_with_collocations("банкир") == []
    assert expand_query_with_collocations("банк") == ["мировой банк"]


def test_query_expansion_skips_short_ambiguous_terms(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_expansion._load_collocations",
        lambda: [("зал", "суд", 9.0), ("гагаринский", "суд", 8.0)],
    )

    assert expand_query_with_collocations("конституционный суд пенсия") == []


def test_query_expansion_filters_code_like_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_expansion._load_collocations",
        lambda: [
            ("skip", "locked", 12.0, 20),
            ("usr", "bin", 12.0, 20),
            ("diannas", "dontbuild", 12.0, 20),
            ("x-forwarded-for", "proxy_add_x_forwarded_for", 12.0, 20),
            ("дональд", "трамп", 6.5, 800),
        ],
    )

    assert expand_query_with_collocations("трамп") == ["дональд трамп"]


def test_query_expansion_allows_known_short_domain_terms(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_expansion._load_collocations",
        lambda: [("млрд", "руб", 6.0, 100)],
    )

    assert expand_query_with_collocations("руб") == ["млрд руб"]


def test_query_expansion_skips_when_query_already_contains_known_phrase(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_expansion._load_collocations",
        lambda: [
            ("искусственный", "интеллект", 8.0, 300),
            ("технология", "искусственный", 7.0, 100),
        ],
    )

    assert expand_query_with_collocations("искусственный интеллект") == []


def test_rate_limiter_uses_atomic_lua_eval(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self):
            self.eval_calls = []

        def eval(self, script, numkeys, key, window):
            self.eval_calls.append((script, numkeys, key, window))
            return 1

    fake_redis = FakeRedis()
    limiter = RateLimiter(max_requests=2, window_seconds=10)
    monkeypatch.setattr(limiter, "_get_redis", lambda: fake_redis)

    assert limiter.is_allowed("user-1") is True
    assert fake_redis.eval_calls[0][2] == "rate_limit:user-1"
    assert fake_redis.eval_calls[0][3] == 10


def test_pubsub_cache_invalidation_hook(monkeypatch) -> None:
    calls = []

    class FakeCache:
        def invalidate_for_layer_event(self, event):
            calls.append(event)
            return 3

    monkeypatch.setattr("jarvis.retrieval.services.cache_invalidation.SearchCache", FakeCache)

    from jarvis.retrieval.services.cache_invalidation import handle_cache_invalidation_message

    deleted = handle_cache_invalidation_message('{"news_ids": [1, 2]}')

    assert deleted == 3
    assert calls == [{"news_ids": [1, 2]}]
