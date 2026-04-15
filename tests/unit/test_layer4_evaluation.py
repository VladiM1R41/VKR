from __future__ import annotations

from jarvis.personalization.models.evaluation_models import EvaluationScenario
from jarvis.personalization.models.ranking_models import PersonalizedResult, PersonalizedSearchResponse
from jarvis.personalization.services.evaluation_service import PersonalizationEvaluationService
from jarvis.retrieval.models.search_models import SearchResponse, SearchResult


def _baseline_result(news_id: int, source_id: int, topic: str, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=f"chunk-{news_id}",
        news_id=news_id,
        source_id=source_id,
        source_name=f"source-{source_id}",
        title=f"title-{news_id}",
        snippet=f"snippet-{news_id}",
        score=score,
        topics=[topic] if topic else [],
        entities=[],
    )


def _personalized_result(
    news_id: int,
    source_id: int,
    topic: str,
    score: float,
    *,
    reasons: list[str] | None = None,
) -> PersonalizedResult:
    return PersonalizedResult(
        news_id=news_id,
        source_id=source_id,
        source_name=f"source-{source_id}",
        title=f"title-{news_id}",
        snippet=f"snippet-{news_id}",
        base_score=score,
        personalized_score=score,
        topics=[topic] if topic else [],
        entities=[],
        personalization_reasons=list(reasons or []),
    )


def test_evaluation_service_measures_personalized_improvement() -> None:
    service = PersonalizationEvaluationService()
    scenario = EvaluationScenario(
        name="economy-user",
        expected_news_ids=[2],
        blocked_news_ids=[99],
        preferred_topic="Экономика",
        top_k=3,
    )
    baseline = SearchResponse(
        query="цб",
        corrected_query=None,
        intent="FACTUAL",
        total=3,
        search_time_ms=11.0,
        results=[
            _baseline_result(1, 10, "Политика", 0.93),
            _baseline_result(2, 10, "Экономика", 0.90),
            _baseline_result(3, 11, "Технологии", 0.88),
        ],
    )
    personalized = PersonalizedSearchResponse(
        query="цб",
        corrected_query=None,
        intent="FACTUAL",
        total=3,
        results=[
            _personalized_result(2, 10, "Экономика", 1.02, reasons=["topic_match: Экономика"]),
            _personalized_result(1, 10, "Политика", 0.93),
            _personalized_result(3, 11, "Технологии", 0.88),
        ],
    )
    diversified = PersonalizedSearchResponse(
        query="цб",
        corrected_query=None,
        intent="FACTUAL",
        total=3,
        results=[
            _personalized_result(2, 10, "Экономика", 1.02, reasons=["topic_match: Экономика"]),
            _personalized_result(3, 11, "Технологии", 0.89, reasons=["diversity_insertion"]),
            _personalized_result(1, 10, "Политика", 0.93),
        ],
    )

    comparison = service.compare(
        scenario=scenario,
        baseline=baseline,
        personalized=personalized,
        diversified=diversified,
    )

    assert comparison.baseline.reciprocal_rank == 0.5
    assert comparison.personalized.reciprocal_rank == 1.0
    assert comparison.reciprocal_rank_delta == 0.5
    assert comparison.personalized.topical_coverage_at_k == comparison.baseline.topical_coverage_at_k
    assert comparison.diversified.diversity_score_at_k >= comparison.personalized.diversity_score_at_k


def test_evaluation_service_tracks_blocked_and_seen_suppression() -> None:
    service = PersonalizationEvaluationService()
    scenario = EvaluationScenario(
        name="blocked-source-user",
        expected_news_ids=[4],
        blocked_news_ids=[9],
        preferred_topic="Технологии",
        top_k=3,
    )
    response = PersonalizedSearchResponse(
        query="технологии",
        corrected_query=None,
        intent="FACTUAL",
        total=3,
        results=[
            _personalized_result(4, 20, "Технологии", 0.97, reasons=["topic_match: Технологии"]),
            _personalized_result(9, 21, "Технологии", 0.90, reasons=["blocked_source: x"]),
            _personalized_result(5, 22, "Экономика", 0.85, reasons=["seen_penalty_applied"]),
        ],
    )

    metrics = service.evaluate_personalized(response, scenario=scenario)

    assert metrics.hit_at_k == 1.0
    assert metrics.blocked_exposure_at_k == 0.3333
    assert metrics.seen_suppression_score_at_k == 0.6667
