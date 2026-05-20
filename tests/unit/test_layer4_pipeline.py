from __future__ import annotations

from datetime import UTC, datetime

from jarvis.db.models.user import User
from jarvis.personalization.models.ranking_models import PersonalizedResult, PersonalizedSearchResponse
from jarvis.personalization.services.diversity_service import DiversityService
from jarvis.personalization.services.pipeline_service import PersonalizationPipelineService
from jarvis.retrieval.models.search_models import SearchResponse


class FakeSession:
    def __init__(self, *, diversity_slider: float = 0.8) -> None:
        self.user = User(
            id=1,
            username="alice",
            settings={"diversity_slider": diversity_slider},
            created_at=datetime.now(UTC),
        )

    def get(self, model, key):
        if model.__name__ == "User" and key == 1:
            return self.user
        return None


class FakeRankingService:
    def rerank(self, session, user_id: int, response: SearchResponse) -> PersonalizedSearchResponse:
        return PersonalizedSearchResponse(
            query=response.query,
            corrected_query=response.corrected_query,
            intent=response.intent,
            total=4,
            results=[
                _result(1, 10, "Экономика", 0.91),
                _result(2, 10, "Экономика", 0.90),
                _result(3, 10, "Экономика", 0.89),
                _result(4, 11, "Технологии", 0.70),
            ],
        )


def _result(news_id: int, source_id: int, topic: str, score: float) -> PersonalizedResult:
    return PersonalizedResult(
        news_id=news_id,
        source_id=source_id,
        source_name=f"source-{source_id}",
        title=f"title-{news_id}",
        snippet="x",
        base_score=score,
        personalized_score=score,
        topics=[topic],
        entities=[],
    )


def test_personalization_pipeline_applies_diversity_after_rerank() -> None:
    service = PersonalizationPipelineService(
        ranking_service=FakeRankingService(),  # type: ignore[arg-type]
        diversity_service=DiversityService(),
    )
    response = SearchResponse(query="q", corrected_query=None, intent="FACTUAL", total=0, search_time_ms=1.0, results=[])

    personalized = service.personalize(FakeSession(diversity_slider=0.8), user_id=1, response=response)

    assert [item.news_id for item in personalized.results[:3]] == [1, 2, 4]


def test_personalization_pipeline_uses_safe_default_diversity_slider() -> None:
    service = PersonalizationPipelineService(
        ranking_service=FakeRankingService(),  # type: ignore[arg-type]
        diversity_service=DiversityService(),
    )
    response = SearchResponse(query="q", corrected_query=None, intent="FACTUAL", total=0, search_time_ms=1.0, results=[])

    personalized = service.personalize(FakeSession(diversity_slider="bad"), user_id=1, response=response)  # type: ignore[arg-type]

    assert [item.news_id for item in personalized.results[:3]] == [1, 2, 3]
