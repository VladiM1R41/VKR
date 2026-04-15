"""Main search service for Layer 3 — orchestrates full pipeline.

Pipeline:
  query → rate_limit → cache_check → autocorrect → preprocess → expand
    → retrieve (dense+sparse → RRF) → rerank → dedup → final_score → output

Per Platt ch. 3.7: retrieval score and trust score computed separately,
combined only at the final step.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Optional

from jarvis.core.logging import log_event
from jarvis.processing.ir.lemmatize import lemmatize_text
from jarvis.processing.services.embedding_runtime import encode_texts
from jarvis.retrieval.models.search_models import (
    SearchRequest,
    SearchResponse,
    SearchResult as SearchResultModel,
    SearchFilters,
)
from jarvis.retrieval.services.query_preprocessing import preprocess_query
from jarvis.retrieval.services.qdrant_search import QdrantSearchService, SearchResult
from jarvis.retrieval.services.reranking import RerankingService, RerankedResult
from jarvis.retrieval.services.query_autocorrect import autocorrect_query
from jarvis.retrieval.services.query_expansion import expand_query_with_collocations
from jarvis.retrieval.services.cache import SearchCache
from jarvis.retrieval.services.rate_limiter import RateLimiter
from jarvis.retrieval.services.search_logger import SearchLogger


logger = logging.getLogger(__name__)


def compute_final_score(
    rerank_score: float,
    trust_score: float,
    content_grade: int,
    published_at: Optional[datetime],
    zone: str,
) -> float:
    """Combined score per Platt: relevance + trust + freshness + zone boost.

    Each component computed independently, combined only at the end.

    Args:
        rerank_score: Cross-encoder score [0, 1].
        trust_score: Source trust score [0, 1].
        content_grade: Content grade 1-6 (1=best, 6=worst).
        published_at: Publication time.
        zone: 'title' or 'body'.

    Returns:
        Combined score [0, 1].
    """
    # Normalize grade: 1→1.0, 6→0.0
    grade_norm = 1.0 - (content_grade - 1) / 5.0

    # Freshness: exponential decay, half-life 24h
    if published_at:
        age_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
        freshness = math.exp(-math.log(2) * age_hours / 24.0)
    else:
        freshness = 0.5

    # Zone boost: title is more important
    zone_boost = 1.2 if zone == "title" else 1.0

    # Weighted combination
    raw = (
        0.50 * rerank_score +
        0.20 * trust_score +
        0.15 * grade_norm +
        0.15 * freshness
    )

    return min(1.0, raw * zone_boost)


def deduplicate_by_article(results: list[RerankedResult]) -> list[RerankedResult]:
    """Keep only the best chunk per article (news_id).

    Multiple chunks from the same article can appear in retrieval results.
    We keep only the highest-scoring chunk per article.
    """
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
    """Choose a conservative cache TTL bucket from retrieved result types."""
    if not results:
        return "daily"

    priority = {
        "breaking": 0,
        "daily": 1,
        "analytics": 2,
        "reference": 3,
    }
    return min(results, key=lambda item: priority.get(item.information_type, 99)).information_type


class SearchService:
    """Main search orchestration."""

    def __init__(self) -> None:
        self._qdrant = QdrantSearchService()
        self._reranker = RerankingService()
        self._cache = SearchCache()
        self._rate_limiter = RateLimiter()
        self._logger = SearchLogger()

    def search(self, request: SearchRequest, user_id: Optional[str] = None) -> SearchResponse:
        """Execute full search pipeline.

        Args:
            request: SearchRequest with query, limit, filters.
            user_id: Optional user identifier for rate limiting.

        Returns:
            SearchResponse with ranked results and metadata.
        """
        t0 = time.time()

        # Rate limiting
        if user_id and not self._rate_limiter.is_allowed(user_id):
            return SearchResponse(
                query=request.query,
                intent="FACTUAL",
                results=[],
                total=0,
                search_time_ms=0.0,
            )

        # Check cache
        filters_hash = str(sorted((request.filters or SearchFilters()).model_dump().items()))
        cached = self._cache.get(request.query, filters_hash)
        if cached:
            log_event(logger, logging.INFO, "search_cache_hit", query=request.query[:100])
            return SearchResponse(**cached)

        # Step 0: Autocorrect
        autocorrect = autocorrect_query(request.query)
        effective_query = autocorrect.corrected

        # Step 1: Preprocess query
        ctx = preprocess_query(effective_query)

        # Step 2: Query expansion — get expansion phrases
        expansions = expand_query_with_collocations(ctx.lemma)
        additional_queries = _build_additional_query_vectors(expansions)

        # Step 3: Retrieve (dense + sparse → RRF fusion)
        filters = request.filters or SearchFilters()
        raw_results = self._qdrant.search(
            dense_vector=ctx.dense_vector,
            sparse_indices=ctx.sparse_indices,
            sparse_values=ctx.sparse_values,
            limit=request.limit * 2,  # retrieve more for dedup
            date_from=filters.date_from,
            date_to=filters.date_to,
            source_ids=filters.source_ids,
            topics=filters.topics,
            language=filters.language,
            additional_queries=additional_queries,
        )

        # Step 4: Rerank
        reranked = self._reranker.rerank(effective_query, raw_results)

        # Step 5: Deduplicate by article
        deduped = deduplicate_by_article(reranked)

        # Step 6: Compute final combined score
        final_results: list[SearchResultModel] = []
        for item in deduped[:request.limit]:
            r = item.result
            score = compute_final_score(
                rerank_score=item.rerank_score,
                trust_score=r.trust_score,
                content_grade=r.content_grade,
                published_at=r.published_at,
                zone=r.zone,
            )
            explanation = self._explain(r, effective_query)
            snippet = self._build_snippet(r, effective_query)
            final_results.append(
                SearchResultModel(
                    chunk_id=r.point_id,
                    news_id=r.news_id,
                    source_id=r.source_id,
                    source_name=r.source_name,
                    title=r.title,
                    snippet=snippet,
                    score=round(score, 4),
                    rerank_score=round(item.rerank_score, 4),
                    topics=r.topics,
                    entities=r.entities,
                    published_at=r.published_at,
                    explanation=explanation,
                )
            )

        elapsed_ms = round((time.time() - t0) * 1000, 1)

        response = SearchResponse(
            query=request.query,
            corrected_query=effective_query if autocorrect.was_corrected else None,
            intent=ctx.intent.intent,
            results=final_results,
            total=len(final_results),
            search_time_ms=elapsed_ms,
        )

        # Cache the response
        self._cache.set(
            request.query,
            filters_hash,
            response.model_dump(),
            information_type=_resolve_cache_information_type(raw_results),
        )

        # Log the search
        top_ids = [r.news_id for r in final_results[:5]]
        self._logger.log_search(
            query_text=request.query,
            intent=ctx.intent.intent,
            num_results=len(final_results),
            retrieval_time_ms=int(elapsed_ms),
            top_result_ids=top_ids,
            resolved_query=effective_query if effective_query != request.query else None,
        )

        log_event(
            logger,
            logging.INFO,
            "search_completed",
            query=request.query[:100],
            intent=ctx.intent.intent,
            results_count=len(final_results),
            elapsed_ms=elapsed_ms,
        )
        return response

    def _explain(self, result: SearchResult, query: str) -> str:
        """Build explanation why this result was found."""
        reasons = []
        if result.zone == "title":
            reasons.append("Совпадение в заголовке (повышенный вес)")
        if result.topics:
            reasons.append(f"Тема: {', '.join(result.topics[:2])}")
        if result.entities:
            reasons.append(f"Сущности: {', '.join(result.entities[:3])}")
        reasons.append(f"Надёжность: {result.source_name} (grade={result.content_grade})")
        return " | ".join(reasons) if reasons else None

    def _build_snippet(self, result: SearchResult, query: str) -> str:
        """Build query-dependent snippet with term highlighting."""
        text = result.snippet_lead or result.text
        if not text:
            return result.title
        # Find first sentence containing a query term
        query_terms = set(query.lower().split())
        sentences = text.replace(". ", ".\n").split("\n")
        for sent in sentences:
            if any(term in sent.lower() for term in query_terms):
                snippet = sent.strip()
                return snippet[:200] + ("..." if len(snippet) > 200 else "")
        # Fallback: first 200 chars
        return text[:200] + ("..." if len(text) > 200 else "")
