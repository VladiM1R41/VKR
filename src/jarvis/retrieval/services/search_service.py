"""Main search service for Layer 3.

Pipeline:
  query -> rate_limit -> cache_check -> autocorrect -> preprocess -> expand
    -> retrieve (dense+sparse RRF) -> rerank -> final_score -> output
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Optional

from jarvis.core.logging import log_event
from jarvis.processing.ir.lemmatize import lemmatize_text
from jarvis.processing.services.embedding_runtime import encode_texts
from jarvis.retrieval.models.search_models import (
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SearchResult as SearchResultModel,
)
from jarvis.retrieval.services.cache import SearchCache
from jarvis.retrieval.services.postgres_fts import PostgresFTSSearchService
from jarvis.retrieval.services.qdrant_search import QdrantSearchService, SearchResult
from jarvis.retrieval.services.query_autocorrect import autocorrect_query
from jarvis.retrieval.services.query_expansion import expand_query_with_collocations
from jarvis.retrieval.services.query_preprocessing import preprocess_query
from jarvis.retrieval.services.rate_limiter import RateLimiter
from jarvis.retrieval.services.reranking import RerankedResult, RerankingService
from jarvis.retrieval.services.search_logger import SearchLogger


logger = logging.getLogger(__name__)


def compute_final_score(
    rerank_score: float,
    retrieval_score: float,
    trust_score: float,
    content_grade: int,
    published_at: Optional[datetime],
    zone: str,
    information_type: str = "daily",
    value_score: Optional[float] = None,
    payload_freshness: Optional[float] = None,
) -> float:
    """Combine relevance, trust, grade and freshness only at the final step."""
    grade_norm = 1.0 - (content_grade - 1) / 5.0
    retrieval_score = max(0.0, min(1.0, float(retrieval_score)))
    if abs(rerank_score - 0.5) < 0.01:
        relevance = 0.80 * retrieval_score + 0.20 * rerank_score
    else:
        relevance = 0.70 * rerank_score + 0.30 * retrieval_score

    if payload_freshness is not None:
        freshness = max(0.0, min(1.0, float(payload_freshness)))
    elif published_at:
        half_life_hours = {
            "breaking": 6.0,
            "daily": 24.0,
            "analytics": 24.0 * 7,
            "reference": 24.0 * 30,
        }.get(information_type, 24.0)
        age_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
        freshness = math.exp(-math.log(2) * max(age_hours, 0.0) / half_life_hours)
    else:
        freshness = 0.5

    zone_boost = 1.2 if zone == "title" else 1.0
    raw = (
        0.50 * relevance
        + 0.20 * trust_score
        + 0.15 * grade_norm
        + 0.15 * freshness
    )
    if value_score is not None:
        raw = 0.80 * raw + 0.20 * max(0.0, min(1.0, float(value_score)))
    return min(1.0, raw * zone_boost)


def deduplicate_by_article(results: list[RerankedResult]) -> list[RerankedResult]:
    """Keep the best reranked chunk per article. Kept for compatibility tests."""
    best_per_article: dict[int, RerankedResult] = {}
    for item in results:
        nid = item.result.news_id
        if nid not in best_per_article or item.rerank_score > best_per_article[nid].rerank_score:
            best_per_article[nid] = item
    return sorted(best_per_article.values(), key=lambda x: x.rerank_score, reverse=True)


def _build_additional_query_vectors(expansions: list[str]) -> list[tuple[list[float], list[int], list[float]]]:
    """Encode expansion phrases as extra hybrid queries for fusion."""
    if not expansions:
        return []

    sparse_expansions = [lemmatize_text(expansion) for expansion in expansions]
    encoded = encode_texts(expansions, sparse_texts=sparse_expansions)
    return [
        (item.dense_vector, item.sparse_indices, item.sparse_values)
        for item in encoded
    ]


def _resolve_cache_information_type(results: list[SearchResult]) -> str:
    """Choose the shortest safe cache TTL bucket from retrieved result types."""
    if not results:
        return "daily"

    priority = {
        "breaking": 0,
        "daily": 1,
        "analytics": 2,
        "reference": 3,
    }
    return min(results, key=lambda item: priority.get(item.information_type, 99)).information_type


def _merge_retrieval_candidates(*candidate_lists: list[SearchResult]) -> list[SearchResult]:
    """Merge Qdrant and lexical candidates without duplicating the same point."""
    merged: list[SearchResult] = []
    seen: set[str] = set()
    for candidates in candidate_lists:
        for candidate in candidates:
            key = candidate.point_id
            if key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
    return merged


class SearchService:
    """Main search orchestration."""

    def __init__(self) -> None:
        self._qdrant = QdrantSearchService()
        self._postgres_fts = PostgresFTSSearchService()
        self._reranker = RerankingService()
        self._cache = SearchCache()
        self._rate_limiter = RateLimiter()
        self._logger = SearchLogger()

    @staticmethod
    def _filters_hash(filters: SearchFilters) -> str:
        """Stable representation for cache keys and logs."""
        return json.dumps(filters.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _coerce_user_id(user_id: Optional[str]) -> Optional[int]:
        if user_id is None:
            return None
        value = str(user_id)
        return int(value) if value.isdigit() else None

    @staticmethod
    def _result_rows(results: list[SearchResultModel]) -> list[dict]:
        return [
            {
                "news_id": item.news_id,
                "rank_position": rank,
                "score": item.score,
            }
            for rank, item in enumerate(results, start=1)
        ]

    def search(self, request: SearchRequest, user_id: Optional[str] = None) -> SearchResponse:
        """Execute full search pipeline."""
        t0 = time.time()
        filters = request.filters or SearchFilters()

        if user_id and not self._rate_limiter.is_allowed(user_id):
            return SearchResponse(
                query=request.query,
                intent="FACTUAL",
                results=[],
                total=0,
                search_time_ms=0.0,
            )

        filters_hash = self._filters_hash(filters)
        cached = self._cache.get(request.query, filters_hash)
        if cached:
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            response = SearchResponse(**cached)
            response.search_time_ms = elapsed_ms
            self._logger.log_search(
                query_text=request.query,
                intent=response.intent,
                num_results=response.total,
                retrieval_time_ms=int(elapsed_ms),
                result_rows=self._result_rows(response.results),
                user_id=self._coerce_user_id(user_id),
                resolved_query=response.corrected_query,
                cache_hit=True,
                retrieval_mode="cache",
                search_type=response.intent,
                extra={"filters": filters.model_dump(mode="json")},
            )
            log_event(logger, logging.INFO, "search_cache_hit", query=request.query[:100])
            return response

        autocorrect = autocorrect_query(request.query)
        effective_query = autocorrect.corrected
        ctx = preprocess_query(effective_query)

        expansions = expand_query_with_collocations(ctx.lemma)
        additional_queries = _build_additional_query_vectors(expansions)

        candidate_limit = max(30, min(100, request.limit * 5))
        raw_results = self._qdrant.search(
            dense_vector=ctx.dense_vector,
            sparse_indices=ctx.sparse_indices,
            sparse_values=ctx.sparse_values,
            limit=candidate_limit,
            date_from=filters.date_from,
            date_to=filters.date_to,
            source_ids=filters.source_ids,
            topics=filters.topics,
            zone=filters.zone,
            content_grade=filters.content_grade,
            content_grade_max=filters.content_grade_max,
            urgency=filters.urgency,
            information_type=filters.information_type,
            event_cluster_id=filters.event_cluster_id,
            language=filters.language,
            additional_queries=additional_queries,
        )

        retrieval_mode = "qdrant_hybrid"
        cacheable = True
        qdrant_error = getattr(self._qdrant, "last_error", None)
        if qdrant_error:
            raw_results = self._postgres_fts.search(
                effective_query,
                limit=candidate_limit,
                date_from=filters.date_from,
                date_to=filters.date_to,
                source_ids=filters.source_ids,
                topics=filters.topics,
                language=filters.language,
                zone=filters.zone,
                content_grade=filters.content_grade,
                content_grade_max=filters.content_grade_max,
                urgency=filters.urgency,
                information_type=filters.information_type,
                event_cluster_id=filters.event_cluster_id,
            )
            retrieval_mode = "postgres_fts_fallback"
            cacheable = False
        else:
            lexical_results = self._postgres_fts.search(
                effective_query,
                limit=min(20, candidate_limit),
                date_from=filters.date_from,
                date_to=filters.date_to,
                source_ids=filters.source_ids,
                topics=filters.topics,
                language=filters.language,
                zone=filters.zone,
                content_grade=filters.content_grade,
                content_grade_max=filters.content_grade_max,
                urgency=filters.urgency,
                information_type=filters.information_type,
                event_cluster_id=filters.event_cluster_id,
                retrieval_mode="postgres_fts_supplement",
            )
            if lexical_results:
                raw_results = _merge_retrieval_candidates(raw_results, lexical_results)
                retrieval_mode = "qdrant_hybrid+postgres_fts"

        reranked = self._reranker.rerank(effective_query, raw_results)
        max_retrieval_score = max((item.result.score for item in reranked), default=1.0) or 1.0

        best_per_article: dict[int, SearchResultModel] = {}
        for item in reranked:
            r = item.result
            score = compute_final_score(
                rerank_score=item.rerank_score,
                retrieval_score=r.score / max_retrieval_score,
                trust_score=r.trust_score,
                content_grade=r.content_grade,
                published_at=r.published_at,
                zone=r.zone,
                information_type=r.information_type,
                value_score=r.value_score,
                payload_freshness=r.freshness,
            )
            result_model = SearchResultModel(
                chunk_id=r.point_id,
                news_id=r.news_id,
                source_id=r.source_id,
                source_name=r.source_name,
                title=r.title,
                snippet=self._build_snippet(r, effective_query),
                score=round(score, 4),
                rerank_score=round(item.rerank_score, 4),
                retrieval_score=round(r.score, 4),
                retrieval_mode=r.retrieval_mode or retrieval_mode,
                topics=r.topics,
                entities=r.entities,
                keywords=r.keywords,
                published_at=r.published_at,
                trust_score=r.trust_score,
                content_grade=r.content_grade,
                information_type=r.information_type,
                urgency=r.urgency,
                event_cluster_id=r.event_cluster_id,
                value_score=r.value_score,
                freshness=r.freshness,
                completeness=r.completeness,
                cluster_support=r.cluster_support,
                is_uncertain=r.is_uncertain,
                explanation=self._explain(r, effective_query, expansions, r.retrieval_mode or retrieval_mode),
            )
            previous = best_per_article.get(r.news_id)
            if previous is None or result_model.score > previous.score:
                best_per_article[r.news_id] = result_model

        final_results = sorted(best_per_article.values(), key=lambda item: item.score, reverse=True)[:request.limit]
        elapsed_ms = round((time.time() - t0) * 1000, 1)

        response = SearchResponse(
            query=request.query,
            corrected_query=effective_query if autocorrect.was_corrected else None,
            intent=ctx.intent.intent,
            results=final_results,
            total=len(final_results),
            search_time_ms=elapsed_ms,
        )

        if cacheable:
            self._cache.set(
                request.query,
                filters_hash,
                response.model_dump(),
                information_type=_resolve_cache_information_type(raw_results),
            )

        self._logger.log_search(
            query_text=request.query,
            intent=ctx.intent.intent,
            num_results=len(final_results),
            retrieval_time_ms=int(elapsed_ms),
            result_rows=self._result_rows(final_results),
            user_id=self._coerce_user_id(user_id),
            resolved_query=effective_query if effective_query != request.query else None,
            cache_hit=False,
            retrieval_mode=retrieval_mode,
            search_type=ctx.intent.intent,
            extra={
                "filters": filters.model_dump(mode="json"),
                "expansions": expansions,
                "qdrant_error": qdrant_error,
            },
        )

        log_event(
            logger,
            logging.INFO,
            "search_completed",
            query=request.query[:100],
            intent=ctx.intent.intent,
            results_count=len(final_results),
            elapsed_ms=elapsed_ms,
            retrieval_mode=retrieval_mode,
        )
        return response

    def _explain(
        self,
        result: SearchResult,
        query: str,
        expansions: list[str] | None = None,
        retrieval_mode: str = "qdrant_hybrid",
    ) -> str:
        """Build a concise explanation why this result was found."""
        reasons = [f"retrieval={retrieval_mode}"]
        if expansions:
            reasons.append(f"expansion={', '.join(expansions[:2])}")
        if result.zone == "title":
            reasons.append("match in title")
        if result.topics:
            reasons.append(f"topics={', '.join(result.topics[:2])}")
        if result.entities:
            reasons.append(f"entities={', '.join(result.entities[:3])}")
        if result.keywords:
            reasons.append(f"keywords={', '.join(result.keywords[:3])}")
        if result.is_uncertain:
            reasons.append("uncertain")
        reasons.append(f"source={result.source_name}")
        reasons.append(f"grade={result.content_grade}")
        return " | ".join(reasons)

    def _build_snippet(self, result: SearchResult, query: str) -> str:
        """Build query-dependent snippet with lemma-aware sentence matching."""
        text = result.snippet_lead or result.text
        if not text:
            return result.title

        query_terms = set(lemmatize_text(query).lower().split()) or set(query.lower().split())
        try:
            from razdel import sentenize

            sentences = [text[item.start:item.stop].strip() for item in sentenize(text)]
        except Exception:
            sentences = text.replace(". ", ".\n").split("\n")

        for sentence in sentences:
            sentence_terms = set(lemmatize_text(sentence).lower().split())
            if query_terms & sentence_terms:
                snippet = sentence.strip()
                return snippet[:200] + ("..." if len(snippet) > 200 else "")

        return text[:200] + ("..." if len(text) > 200 else "")
