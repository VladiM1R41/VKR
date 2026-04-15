"""Bridge from Layer 3 retrieval results to Layer 5 generation context."""

from __future__ import annotations

from jarvis.generation.services.context_assembler import NewsWithContext, enrich_with_db_data
from jarvis.retrieval.models.search_models import SearchFilters, SearchRequest
from jarvis.retrieval.services.search_service import SearchService


class RetrievalBridge:
    """Load Layer 3 search results as Layer 5 NewsWithContext objects."""

    def __init__(self, search_service: SearchService | None = None) -> None:
        self._search_service = search_service or SearchService()

    def retrieve_news_context(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[NewsWithContext]:
        response = self._search_service.search(
            SearchRequest(
                query=query,
                limit=limit,
                filters=filters,
            )
        )
        results = response.results
        news_ids = [item.news_id for item in results]
        source_ids = {item.source_id for item in results}
        titles = {item.news_id: item.title for item in results}
        snippets = {item.news_id: item.snippet for item in results}
        scores = {item.news_id: item.score for item in results}
        rerank_scores = {item.news_id: item.rerank_score for item in results}
        personalized_scores = {item.news_id: None for item in results}
        topics_map = {item.news_id: list(item.topics) for item in results}
        entities_map = {item.news_id: list(item.entities) for item in results}
        published_map = {
            item.news_id: item.published_at.isoformat() if item.published_at else ""
            for item in results
        }
        trust_map = {item.news_id: 0.5 for item in results}
        grade_map = {item.news_id: 6 for item in results}
        info_type_map = {item.news_id: "daily" for item in results}
        urgency_map = {item.news_id: "normal" for item in results}
        cluster_map = {item.news_id: None for item in results}
        return enrich_with_db_data(
            news_ids=news_ids,
            source_ids=source_ids,
            titles=titles,
            snippets=snippets,
            scores=scores,
            rerank_scores=rerank_scores,
            personalized_scores=personalized_scores,
            topics_map=topics_map,
            entities_map=entities_map,
            published_map=published_map,
            trust_map=trust_map,
            grade_map=grade_map,
            info_type_map=info_type_map,
            urgency_map=urgency_map,
            cluster_map=cluster_map,
        )
