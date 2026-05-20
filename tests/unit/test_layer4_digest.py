from __future__ import annotations

from datetime import UTC, datetime

from jarvis.personalization.models.ranking_models import PersonalizedResult, PersonalizedSearchResponse
from jarvis.personalization.services.digest_service import DigestOrchestrationService


class ScalarRows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self) -> None:
        self.previous_digests = [
            type(
                "DigestStub",
                (),
                {
                    "id": 1,
                    "user_id": 7,
                    "digest_type": "morning",
                    "topics_covered": ["Экономика"],
                    "generated_at": datetime.now(UTC),
                },
            )()
        ]
        self.previous_news_ids = [101]
        self.existing_hash = None
        self.added = []
        self.flush_called = False
        self.committed = False
        self.next_digest_id = 10

    def scalars(self, stmt):
        text = str(stmt)
        if "FROM digests" in text and "ORDER BY digests.generated_at DESC" in text:
            return ScalarRows(self.previous_digests)
        if "FROM digest_items" in text:
            return ScalarRows(self.previous_news_ids)
        raise AssertionError(text)

    def scalar(self, stmt):
        return self.existing_hash

    def add(self, obj):
        if getattr(obj, "__tablename__", "") == "digests" and getattr(obj, "id", None) is None:
            obj.id = self.next_digest_id
            self.next_digest_id += 1
        self.added.append(obj)

    def flush(self):
        self.flush_called = True

    def commit(self):
        self.committed = True


def _result(news_id: int, topic: str, score: float = 0.9) -> PersonalizedResult:
    return PersonalizedResult(
        news_id=news_id,
        source_id=1,
        source_name="РБК",
        title=f"title-{news_id}",
        snippet=f"snippet-{news_id}",
        base_score=score,
        personalized_score=score,
        topics=[topic],
        entities=[],
        personalization_reasons=["topic_match: x"],
    )


def test_digest_shortlist_skips_previous_digest_items_and_tracks_continuity() -> None:
    session = FakeSession()
    service = DigestOrchestrationService()
    ranked = PersonalizedSearchResponse(
        query="q",
        corrected_query=None,
        intent="FACTUAL",
        total=3,
        results=[
            _result(101, "Экономика"),
            _result(102, "Политика"),
            _result(103, "Технологии"),
        ],
    )

    shortlist = service.build_shortlist(
        session,
        user_id=7,
        digest_type="morning",
        ranked_response=ranked,
        limit=2,
    )

    assert [item.news_id for item in shortlist.candidates] == [102, 103]
    assert "continuity_new_topic: Политика" in shortlist.candidates[0].reasons
    assert shortlist.topics_covered == ["Политика", "Технологии"]


def test_digest_shortlist_detects_duplicate_hash() -> None:
    session = FakeSession()
    session.existing_hash = 99
    service = DigestOrchestrationService()
    ranked = PersonalizedSearchResponse(
        query="q",
        corrected_query=None,
        intent="FACTUAL",
        total=1,
        results=[_result(102, "Политика")],
    )

    shortlist = service.build_shortlist(
        session,
        user_id=7,
        digest_type="morning",
        ranked_response=ranked,
        limit=1,
    )

    assert shortlist.is_duplicate_of_existing is True


def test_digest_shortlist_fills_from_fallback_when_needed() -> None:
    session = FakeSession()
    session.previous_news_ids = [101, 102]
    service = DigestOrchestrationService()
    ranked = PersonalizedSearchResponse(
        query="q",
        corrected_query=None,
        intent="FACTUAL",
        total=3,
        results=[
            _result(101, "Экономика"),
            _result(102, "Политика"),
            _result(103, "Экономика"),
        ],
    )

    shortlist = service.build_shortlist(
        session,
        user_id=7,
        digest_type="morning",
        ranked_response=ranked,
        limit=2,
    )

    assert shortlist.candidates[0].news_id == 103
    assert shortlist.candidates[1].news_id in {101, 102}
    assert "fallback_fill" in shortlist.candidates[1].reasons


def test_digest_shortlist_can_be_persisted() -> None:
    session = FakeSession()
    service = DigestOrchestrationService()
    shortlist = service.build_shortlist(
        session,
        user_id=7,
        digest_type="morning",
        ranked_response=PersonalizedSearchResponse(
            query="q",
            corrected_query=None,
            intent="FACTUAL",
            total=2,
            results=[_result(102, "РџРѕР»РёС‚РёРєР°"), _result(103, "РўРµС…РЅРѕР»РѕРіРёРё")],
        ),
        limit=2,
    )

    digest = service.persist_shortlist(session, shortlist=shortlist, content_text="digest text")

    assert digest.id == 10
    assert digest.content_text == "digest text"
    assert digest.generated_at is not None
    assert session.flush_called is True
    assert session.committed is True
    assert len(session.added) == 3
