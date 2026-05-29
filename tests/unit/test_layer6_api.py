from __future__ import annotations

from fastapi.testclient import TestClient

from jarvis.app.api.v1.digest import _digest_search_filters, _digest_search_query, _restrict_shortlist_topics
from jarvis.app.main import app
from jarvis.app.schemas.digest import DigestGenerateRequest
from jarvis.personalization.models.digest_models import DigestCandidate, DigestShortlist


def test_layer6_openapi_contains_core_routes() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "Newscope API"
    assert "/api/v1/news/feed" in schema["paths"]
    assert "/api/v1/news/sources" in schema["paths"]
    assert "/api/v1/news/topics" in schema["paths"]
    assert "/api/v1/search" in schema["paths"]
    assert "/api/v1/chat" in schema["paths"]
    assert "/api/v1/admin/overview" in schema["paths"]


def test_layer6_openapi_describes_entity_and_audio_contracts() -> None:
    schema = app.openapi()

    trending_response = schema["paths"]["/api/v1/entities/trending"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    detail_response = schema["paths"]["/api/v1/entities/{entity_id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    audio_responses = schema["paths"]["/api/v1/digest/audio"]["get"]["responses"]

    assert trending_response["$ref"] == "#/components/schemas/TrendingEntitiesResponse"
    assert detail_response["$ref"] == "#/components/schemas/EntityDetailResponse"
    assert "audio/wav" in audio_responses["200"]["content"]
    assert "application/json" not in audio_responses["200"]["content"]
    assert (
        audio_responses["202"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/DigestAudioStatusResponse"
    )


def test_layer6_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_digest_generate_request_builds_topic_and_period_filters() -> None:
    request = DigestGenerateRequest(query="технологии", topics=["Технологии"], period_hours=24)

    filters = _digest_search_filters(request)

    assert filters is not None
    assert filters.topics == ["Технологии"]
    assert filters.date_from is not None
    assert filters.content_grade_max == 5


def test_digest_search_query_uses_selected_topics_without_period_words() -> None:
    request = DigestGenerateRequest(
        query="Экономика за последние 24 часов",
        topics=["Экономика"],
        period_hours=24,
    )

    assert _digest_search_query(request) == "Экономика"


def test_digest_shortlist_topics_are_restricted_to_selected_topics() -> None:
    shortlist = DigestShortlist(
        user_id=1,
        digest_type="on_demand",
        content_hash="hash",
        candidates=[
            DigestCandidate(
                news_id=1,
                title="Новость",
                source_name="Источник",
                position=1,
                score=1.0,
                topics=["Технологии", "Политика"],
            )
        ],
    )

    _restrict_shortlist_topics(shortlist, ["Технологии"])

    assert shortlist.candidates[0].topics == ["Технологии"]
    assert shortlist.topics_covered == ["Технологии"]
