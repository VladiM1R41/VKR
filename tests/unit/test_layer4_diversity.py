from __future__ import annotations

from jarvis.personalization.models.ranking_models import PersonalizedResult, PersonalizedSearchResponse
from jarvis.personalization.services.diversity_service import DiversityService


def _result(news_id: int, source_id: int, topic: str, score: float) -> PersonalizedResult:
    return PersonalizedResult(
        news_id=news_id,
        source_id=source_id,
        source_name=f"source-{source_id}",
        title=f"title-{news_id}",
        snippet="x",
        base_score=score,
        personalized_score=score,
        topics=[topic] if topic else [],
        entities=[],
        personalization_reasons=[],
    )


def test_diversity_caps_reorder_repetitive_results() -> None:
    service = DiversityService()
    response = PersonalizedSearchResponse(
        query="q",
        corrected_query=None,
        intent="FACTUAL",
        total=4,
        results=[
            _result(1, 10, "Экономика", 0.91),
            _result(2, 10, "Экономика", 0.89),
            _result(3, 10, "Экономика", 0.88),
            _result(4, 11, "Технологии", 0.70),
        ],
    )

    diversified = service.apply(response, diversity_slider=0.8)

    assert diversified.results[0].news_id == 1
    assert [item.news_id for item in diversified.results[:3]] == [1, 2, 4]


def test_diversity_insertion_marks_reason() -> None:
    service = DiversityService()
    response = PersonalizedSearchResponse(
        query="q",
        corrected_query=None,
        intent="FACTUAL",
        total=4,
        results=[
            _result(1, 10, "Экономика", 0.91),
            _result(2, 10, "Экономика", 0.90),
            _result(3, 11, "Политика", 0.899),
            _result(4, 12, "Технологии", 0.88),
        ],
    )

    diversified = service.apply(response, diversity_slider=0.8)

    assert diversified.results[1].news_id == 3
    assert "diversity_insertion" in diversified.results[1].personalization_reasons


def test_diversity_insertion_does_not_promote_much_weaker_result() -> None:
    service = DiversityService()
    response = PersonalizedSearchResponse(
        query="q",
        corrected_query=None,
        intent="FACTUAL",
        total=4,
        results=[
            _result(1, 10, "Р­РєРѕРЅРѕРјРёРєР°", 0.91),
            _result(2, 10, "Р­РєРѕРЅРѕРјРёРєР°", 0.90),
            _result(3, 11, "РџРѕР»РёС‚РёРєР°", 0.87),
            _result(4, 12, "РўРµС…РЅРѕР»РѕРіРёРё", 0.86),
        ],
    )

    diversified = service.apply(response, diversity_slider=0.8)

    assert [item.news_id for item in diversified.results[:3]] == [1, 2, 3]
    assert "diversity_insertion" not in diversified.results[2].personalization_reasons


def test_low_diversity_slider_is_less_aggressive() -> None:
    service = DiversityService()
    response = PersonalizedSearchResponse(
        query="q",
        corrected_query=None,
        intent="FACTUAL",
        total=4,
        results=[
            _result(1, 10, "Экономика", 0.91),
            _result(2, 10, "Экономика", 0.90),
            _result(3, 10, "Экономика", 0.89),
            _result(4, 11, "Политика", 0.70),
        ],
    )

    diversified = service.apply(response, diversity_slider=0.1)

    assert [item.news_id for item in diversified.results[:3]] == [1, 2, 3]
