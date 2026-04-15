"""Diversity layer for personalized ranking."""

from __future__ import annotations

from collections import Counter

from jarvis.personalization.models.ranking_models import PersonalizedResult, PersonalizedSearchResponse


class DiversityService:
    """Apply anti-filter-bubble rules over personalized results."""

    def __init__(self, *, top_k_window: int = 10) -> None:
        self._top_k_window = top_k_window

    def apply(
        self,
        response: PersonalizedSearchResponse,
        *,
        diversity_slider: float,
    ) -> PersonalizedSearchResponse:
        """Apply caps and diversity insertion over ranked results."""
        if not response.results:
            return response

        slider = max(0.0, min(1.0, diversity_slider))
        topic_cap = 3 if slider < 0.4 else 2
        source_cap = 3 if slider < 0.4 else 2
        enforce_insertion = slider >= 0.35

        selected: list[PersonalizedResult] = []
        deferred: list[PersonalizedResult] = []
        topic_counter: Counter[str] = Counter()
        source_counter: Counter[int] = Counter()

        for result in response.results:
            if self._violates_caps(result, topic_counter, source_counter, topic_cap, source_cap):
                deferred.append(result)
                continue
            selected.append(result)
            self._touch_counters(result, topic_counter, source_counter)

        selected.extend(deferred)

        if enforce_insertion:
            selected = self._ensure_diversity_insertion(selected)

        return PersonalizedSearchResponse(
            query=response.query,
            corrected_query=response.corrected_query,
            intent=response.intent,
            total=len(selected),
            results=selected,
        )

    @staticmethod
    def _violates_caps(
        result: PersonalizedResult,
        topic_counter: Counter[str],
        source_counter: Counter[int],
        topic_cap: int,
        source_cap: int,
    ) -> bool:
        if source_counter[result.source_id] >= source_cap:
            return True
        if result.topics and any(topic_counter[topic] >= topic_cap for topic in result.topics):
            return True
        return False

    @staticmethod
    def _touch_counters(
        result: PersonalizedResult,
        topic_counter: Counter[str],
        source_counter: Counter[int],
    ) -> None:
        source_counter[result.source_id] += 1
        for topic in result.topics:
            topic_counter[topic] += 1

    def _ensure_diversity_insertion(self, results: list[PersonalizedResult]) -> list[PersonalizedResult]:
        if len(results) < 3:
            return results

        window = results[: min(self._top_k_window, len(results))]
        seen_sources = {window[0].source_id}
        seen_topics = set(window[0].topics)

        insertion_idx = None
        for idx in range(1, len(window)):
            candidate = window[idx]
            source_fresh = candidate.source_id not in seen_sources
            topic_fresh = any(topic not in seen_topics for topic in candidate.topics) or not candidate.topics
            if source_fresh or topic_fresh:
                insertion_idx = idx
                break
            seen_sources.add(candidate.source_id)
            seen_topics.update(candidate.topics)

        if insertion_idx is None or insertion_idx <= 1:
            return results

        candidate = results.pop(insertion_idx)
        candidate.personalization_reasons = [
            *candidate.personalization_reasons,
            "diversity_insertion",
        ]
        results.insert(1, candidate)
        return results
