"""Offline evaluation and calibration helpers for Layer 4."""

from __future__ import annotations

from jarvis.personalization.models.evaluation_models import (
    EvaluationComparison,
    EvaluationMetrics,
    EvaluationScenario,
)
from jarvis.personalization.models.ranking_models import PersonalizedSearchResponse
from jarvis.retrieval.models.search_models import SearchResponse


class PersonalizationEvaluationService:
    """Compute lightweight offline metrics for Layer 4 ranking quality."""

    def evaluate_personalized(
        self,
        response: PersonalizedSearchResponse,
        *,
        scenario: EvaluationScenario,
    ) -> EvaluationMetrics:
        """Evaluate a personalized or diversified ranking response."""
        top_k = min(scenario.top_k, len(response.results))
        results = response.results[:top_k]

        expected_set = {int(value) for value in scenario.expected_news_ids}
        blocked_set = {int(value) for value in scenario.blocked_news_ids}
        seen_penalized = sum(
            1 for result in results if "seen_penalty_applied" in result.personalization_reasons
        )
        unique_sources = {result.source_id for result in results}
        unique_topics = {topic for result in results for topic in result.topics}

        hit_at_k = 1.0 if any(result.news_id in expected_set for result in results) else 0.0
        reciprocal_rank = self._reciprocal_rank(
            [result.news_id for result in results],
            expected_set,
        )
        blocked_exposure_at_k = self._ratio(
            sum(1 for result in results if result.news_id in blocked_set),
            top_k,
        )
        topical_coverage_at_k = self._topic_coverage(results, scenario.preferred_topic)
        diversity_score_at_k = self._diversity_score(top_k, len(unique_sources), len(unique_topics))
        seen_suppression_score_at_k = 1.0 - self._ratio(seen_penalized, top_k)

        return EvaluationMetrics(
            hit_at_k=round(hit_at_k, 4),
            reciprocal_rank=round(reciprocal_rank, 4),
            blocked_exposure_at_k=round(blocked_exposure_at_k, 4),
            topical_coverage_at_k=round(topical_coverage_at_k, 4),
            diversity_score_at_k=round(diversity_score_at_k, 4),
            seen_suppression_score_at_k=round(seen_suppression_score_at_k, 4),
        )

    def evaluate_baseline(
        self,
        response: SearchResponse,
        *,
        scenario: EvaluationScenario,
    ) -> EvaluationMetrics:
        """Evaluate raw Layer 3 ordering with the same metric set."""
        top_k = min(scenario.top_k, len(response.results))
        results = response.results[:top_k]

        expected_set = {int(value) for value in scenario.expected_news_ids}
        blocked_set = {int(value) for value in scenario.blocked_news_ids}
        unique_sources = {result.source_id for result in results}
        unique_topics = {topic for result in results for topic in result.topics}

        hit_at_k = 1.0 if any(result.news_id in expected_set for result in results) else 0.0
        reciprocal_rank = self._reciprocal_rank(
            [result.news_id for result in results],
            expected_set,
        )
        blocked_exposure_at_k = self._ratio(
            sum(1 for result in results if result.news_id in blocked_set),
            top_k,
        )
        topical_coverage_at_k = self._topic_coverage(results, scenario.preferred_topic)
        diversity_score_at_k = self._diversity_score(top_k, len(unique_sources), len(unique_topics))

        return EvaluationMetrics(
            hit_at_k=round(hit_at_k, 4),
            reciprocal_rank=round(reciprocal_rank, 4),
            blocked_exposure_at_k=round(blocked_exposure_at_k, 4),
            topical_coverage_at_k=round(topical_coverage_at_k, 4),
            diversity_score_at_k=round(diversity_score_at_k, 4),
            seen_suppression_score_at_k=1.0,
        )

    def compare(
        self,
        *,
        scenario: EvaluationScenario,
        baseline: SearchResponse,
        personalized: PersonalizedSearchResponse,
        diversified: PersonalizedSearchResponse,
    ) -> EvaluationComparison:
        """Compare baseline vs personalized vs personalized+diversity."""
        baseline_metrics = self.evaluate_baseline(baseline, scenario=scenario)
        personalized_metrics = self.evaluate_personalized(personalized, scenario=scenario)
        diversified_metrics = self.evaluate_personalized(diversified, scenario=scenario)

        return EvaluationComparison(
            scenario_name=scenario.name,
            baseline=baseline_metrics,
            personalized=personalized_metrics,
            diversified=diversified_metrics,
            hit_at_k_delta=round(diversified_metrics.hit_at_k - baseline_metrics.hit_at_k, 4),
            reciprocal_rank_delta=round(
                diversified_metrics.reciprocal_rank - baseline_metrics.reciprocal_rank,
                4,
            ),
            blocked_exposure_delta=round(
                diversified_metrics.blocked_exposure_at_k - baseline_metrics.blocked_exposure_at_k,
                4,
            ),
            diversity_score_delta=round(
                diversified_metrics.diversity_score_at_k - baseline_metrics.diversity_score_at_k,
                4,
            ),
        )

    @staticmethod
    def _reciprocal_rank(news_ids: list[int], expected_set: set[int]) -> float:
        if not expected_set:
            return 0.0
        for idx, news_id in enumerate(news_ids, start=1):
            if news_id in expected_set:
                return 1.0 / idx
        return 0.0

    @staticmethod
    def _ratio(value: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return value / total

    @classmethod
    def _diversity_score(cls, total: int, unique_sources: int, unique_topics: int) -> float:
        if total <= 0:
            return 0.0
        return min(1.0, (0.5 * cls._ratio(unique_sources, total)) + (0.5 * cls._ratio(unique_topics, total)))

    @staticmethod
    def _topic_coverage(results: list, preferred_topic: str | None) -> float:
        if not preferred_topic or not results:
            return 0.0
        covered = sum(1 for result in results if preferred_topic in result.topics)
        return covered / len(results)

