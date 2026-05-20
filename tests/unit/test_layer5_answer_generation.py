from __future__ import annotations

from dataclasses import dataclass

from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationConfig,
)
from jarvis.generation.services.chat_memory_service import ChatMemoryService
from jarvis.generation.services.context_assembler import NewsWithContext
from jarvis.generation.services.providers.base import LLMProvider


class _AsyncFakeProvider(LLMProvider):
    def __init__(self, content: str) -> None:
        super().__init__(ProviderConfig(provider_name="fake", model_name="fake-model"))
        self._content = content

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        return LLMGenerationResponse(
            provider_name="fake",
            model_name="fake-model",
            content=self._content,
            input_tokens=100,
            output_tokens=20,
            latency_ms=5,
        )


class _NeverCalledProvider(_AsyncFakeProvider):
    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        raise AssertionError("Provider should not be called on cache hit")


class _SequenceProvider(LLMProvider):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(ProviderConfig(provider_name="fake", model_name="fake-model"))
        self._responses = list(responses)
        self.requests: list[LLMGenerationRequest] = []

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        self.requests.append(request)
        content = self._responses.pop(0)
        return LLMGenerationResponse(
            provider_name="fake",
            model_name="fake-model",
            content=content,
            input_tokens=100,
            output_tokens=20,
            latency_ms=5,
        )


class _NoCache:
    def get(self, **kwargs):
        return None

    def set(self, **kwargs) -> None:
        return None


def _make_news_item(
    *,
    news_id: int,
    source_name: str,
    title: str,
    content: str,
    score: float = 0.9,
    personalized_score: float | None = None,
    event_cluster_id: int | None = None,
    trust_score: float = 0.9,
    content_grade: int = 2,
) -> NewsWithContext:
    return NewsWithContext(
        news_id=news_id,
        source_id=1,
        source_name=source_name,
        title=title,
        content=content,
        snippet_lead=content[:50],
        score=score,
        rerank_score=score,
        personalized_score=personalized_score,
        topics=["economy"],
        entities=["цб"],
        published_at_str="2026-04-15",
        trust_score=trust_score,
        content_grade=content_grade,
        information_type="daily",
        urgency="normal",
        event_cluster_id=event_cluster_id,
    )


def test_generate_answer_works_with_async_provider() -> None:
    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Ставка выросла (ТАСС)."),
        config=GenerationConfig(enable_logging=False),
    )

    result = service.generate_answer(
        user_query="Что со ставкой?",
        news_items=[
            _make_news_item(
                news_id=101,
                source_name="ТАСС",
                title="ЦБ повысил ставку",
                content="ЦБ повысил ставку на заседании.",
            )
        ],
        intent="FACTUAL",
    )

    assert result.answer_text == "Ставка выросла (ТАСС)."
    assert result.model_name == "fake-model"
    assert result.sources[0].news_id == 101
    assert result.citation_valid is True


def test_generate_answer_applies_second_llm_correction_when_quality_improves(monkeypatch) -> None:
    captured = {}

    def _fake_save_generation_log(entry):
        captured["entry"] = entry

        @dataclass
        class _Result:
            log_id: int = 92

        return _Result()

    monkeypatch.setattr(
        "jarvis.generation.services.answer_generation_service.save_generation_log",
        _fake_save_generation_log,
    )
    provider = _SequenceProvider(
        [
            "Martians built a bridge without evidence.",
            "The central bank raised the rate after the meeting [Doc 1].",
        ]
    )
    service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=True),
    )
    service._response_cache = _NoCache()

    result = service.generate_answer(
        user_query="What happened with the rate?",
        news_items=[
            _make_news_item(
                news_id=201,
                source_name="TASS",
                title="Central bank raised the rate",
                content="The central bank raised the rate after the meeting.",
            )
        ],
        intent="FACTUAL",
    )

    assert len(provider.requests) == 2
    assert "Исправь предыдущий ответ" in provider.requests[1].user_prompt
    assert result.answer_text == "The central bank raised the rate after the meeting [Doc 1]."
    assert result.citation_valid is True
    assert result.has_unsupported_claims is False
    assert captured["entry"].documents_used[-1]["meta"]["correction_attempted"] is True
    assert captured["entry"].documents_used[-1]["meta"]["correction_applied"] is True


def test_generate_answer_keeps_original_when_second_llm_correction_is_not_better() -> None:
    provider = _SequenceProvider(
        [
            "Martians built a bridge without evidence.",
            "Venus engineers built a tunnel without evidence.",
        ]
    )
    service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=False),
    )
    service._response_cache = _NoCache()

    result = service.generate_answer(
        user_query="What happened with the rate?",
        news_items=[
            _make_news_item(
                news_id=202,
                source_name="TASS",
                title="Central bank raised the rate",
                content="The central bank raised the rate after the meeting.",
            )
        ],
        intent="FACTUAL",
    )

    assert len(provider.requests) == 2
    assert result.answer_text == "Martians built a bridge without evidence."
    assert result.citation_valid is False
    assert result.has_unsupported_claims is True


def test_generate_digest_logs_real_news_ids(monkeypatch) -> None:
    captured = {}

    def _fake_save_generation_log(entry):
        captured["entry"] = entry

        @dataclass
        class _Result:
            log_id: int = 77

        return _Result()

    monkeypatch.setattr(
        "jarvis.generation.services.answer_generation_service.save_generation_log",
        _fake_save_generation_log,
    )

    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Дайджест дня (ТАСС)."),
        config=GenerationConfig(enable_logging=True),
    )

    result = service.generate_digest(
        news_items=[
            _make_news_item(
                news_id=501,
                source_name="ТАСС",
                title="Главное событие",
                content="Произошло главное событие дня.",
                personalized_score=0.95,
                event_cluster_id=11,
            )
        ],
        user_id=1,
    )

    assert result.generation_log_id == 77
    assert captured["entry"].documents_used[0]["news_id"] == 501
    assert captured["entry"].documents_used[-1]["meta"]["generation_mode"] == "digest"


def test_generate_digest_applies_quality_gate(monkeypatch) -> None:
    captured = {}

    def _fake_save_generation_log(entry):
        captured["entry"] = entry

        @dataclass
        class _Result:
            log_id: int = 78

        return _Result()

    monkeypatch.setattr(
        "jarvis.generation.services.answer_generation_service.save_generation_log",
        _fake_save_generation_log,
    )

    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Марсиане построили мост без подтверждения."),
        config=GenerationConfig(enable_logging=True),
    )

    result = service.generate_digest(
        news_items=[
            _make_news_item(
                news_id=502,
                source_name="ТАСС",
                title="Главное событие",
                content="Произошло главное событие дня.",
                personalized_score=0.95,
                event_cluster_id=12,
            )
        ],
        user_id=1,
    )

    assert result.citation_valid is False
    assert result.has_unsupported_claims is True
    assert result.confidence == "LOW"
    assert captured["entry"].confidence == "LOW"
    assert captured["entry"].documents_used[-1]["meta"]["groundedness_score"] < 0.45


def test_generate_alert_uses_quality_confidence_not_hardcoded_high() -> None:
    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("ЦБ повысил ставку на заседании (ТАСС)."),
        config=GenerationConfig(enable_logging=False),
    )

    result = service.generate_alert(
        news_item=_make_news_item(
            news_id=601,
            source_name="ТАСС",
            title="ЦБ повысил ставку",
            content="ЦБ повысил ставку на заседании.",
        ),
        alert_reason="важная новость по ЦБ",
        user_id=1,
    )

    assert result.confidence == "MEDIUM"
    assert result.citation_valid is True
    assert result.has_unsupported_claims is False


def test_generate_answer_uses_response_cache(monkeypatch) -> None:
    service = AnswerGenerationService(
        provider=_NeverCalledProvider("unused"),
        config=GenerationConfig(enable_logging=False),
    )

    class _FakeCache:
        def get(self, *, mode, rag_mode="standard", query, document_ids, **kwargs):
            return {
                "answer_text": "Кэшированный ответ",
                "rag_mode": "factual",
                "model_name": "cache-model",
                "confidence": "HIGH",
                "input_tokens": 10,
                "output_tokens": 5,
                "citation_valid": True,
                "groundedness_score": 1.0,
                "has_unsupported_claims": False,
            }

        def set(self, **kwargs):
            raise AssertionError("Cache set should not be called on cache hit")

    service._response_cache = _FakeCache()

    result = service.generate_answer(
        user_query="Что со ставкой?",
        news_items=[
            _make_news_item(
                news_id=101,
                source_name="ТАСС",
                title="ЦБ повысил ставку",
                content="ЦБ повысил ставку на заседании.",
            )
        ],
    )

    assert result.answer_text == "Кэшированный ответ"
    assert result.model_name == "cache-model"
    assert result.latency_ms >= 0


def test_generate_answer_logs_response_cache_hit(monkeypatch) -> None:
    captured = {}

    def _fake_save_generation_log(entry):
        captured["entry"] = entry

        @dataclass
        class _Result:
            log_id: int = 91

        return _Result()

    monkeypatch.setattr(
        "jarvis.generation.services.answer_generation_service.save_generation_log",
        _fake_save_generation_log,
    )

    service = AnswerGenerationService(
        provider=_NeverCalledProvider("unused"),
        config=GenerationConfig(enable_logging=True),
    )

    class _FakeCache:
        def get(self, *, mode, rag_mode="standard", query, document_ids, **kwargs):
            return {
                "answer_text": "Кэшированный ответ",
                "rag_mode": rag_mode,
                "model_name": "cache-model",
                "confidence": "HIGH",
                "input_tokens": 10,
                "output_tokens": 5,
                "citation_valid": True,
                "groundedness_score": 1.0,
                "has_unsupported_claims": False,
            }

        def set(self, **kwargs):
            raise AssertionError("Cache set should not be called on cache hit")

    service._response_cache = _FakeCache()

    result = service.generate_answer(
        user_query="Что со ставкой?",
        news_items=[
            _make_news_item(
                news_id=101,
                source_name="ТАСС",
                title="ЦБ повысил ставку",
                content="ЦБ повысил ставку на заседании.",
            )
        ],
    )

    assert result.generation_log_id == 91
    assert captured["entry"].answer_text == "Кэшированный ответ"
    assert captured["entry"].documents_used[-1]["meta"]["cache_hit"] is True


class _FakeChatSession:
    id = 10


class _FakeChatService:
    def __init__(self) -> None:
        self.assistant_messages: list[str] = []

    def get_or_create_session(self, db_session, *, user_id, session_id=None, title=None):
        return _FakeChatSession()

    def save_user_message(self, db_session, *, session_id, content):
        return None

    def save_assistant_message(self, db_session, *, session_id, content, generation_log_id=None):
        self.assistant_messages.append(content)
        return None

    def update_session_title(self, db_session, *, session_id, title):
        return None


def test_generate_chat_answer_crag_uses_retrieval_bridge(monkeypatch) -> None:
    retrieved_item = _make_news_item(
        news_id=702,
        source_name="РўРђРЎРЎ",
        title="Р¦Р‘ РїРѕРІС‹СЃРёР» СЃС‚Р°РІРєСѓ",
        content="Р¦Р‘ РїРѕРІС‹СЃРёР» СЃС‚Р°РІРєСѓ РЅР° Р·Р°СЃРµРґР°РЅРёРё.",
        trust_score=0.95,
        content_grade=1,
    )
    calls: list[str] = []

    class _FakeBridge:
        def retrieve_news_context(self, *, query, limit=10, filters=None):
            calls.append(query)
            return [retrieved_item]

    monkeypatch.setattr("jarvis.generation.services.retrieval_bridge.RetrievalBridge", lambda: _FakeBridge())

    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Р¦Р‘ РїРѕРІС‹СЃРёР» СЃС‚Р°РІРєСѓ РЅР° Р·Р°СЃРµРґР°РЅРёРё (РўРђРЎРЎ)."),
        config=GenerationConfig(enable_logging=False),
        chat_service=_FakeChatService(),
    )

    result = service.generate_chat_answer(
        db_session=object(),
        user_query="Р§С‚Рѕ РёР·РІРµСЃС‚РЅРѕ РїСЂРѕ СЃС‚Р°РІРєСѓ Р¦Р‘?",
        news_items=[
            _make_news_item(
                news_id=701,
                source_name="Bad",
                title="РќРµ СЃРІСЏР·Р°РЅРЅР°СЏ Р·Р°РјРµС‚РєР°",
                content="РљРѕСЂРѕС‚РєРёР№ РЅРµСЂРµР»РµРІР°РЅС‚РЅС‹Р№ С‚РµРєСЃС‚.",
                trust_score=0.1,
                content_grade=6,
            )
        ],
        user_id=1,
        rag_mode_override="crag",
    )

    assert calls
    assert result.rag_mode == "crag"
    assert result.sources[0].news_id == 702


def test_generate_chat_answer_self_rag_uses_retrieval_when_context_irrelevant(monkeypatch) -> None:
    retrieved_item = _make_news_item(
        news_id=802,
        source_name="РўРђРЎРЎ",
        title="Central bank rate",
        content="Central bank raised the rate.",
    )
    calls: list[str] = []

    class _FakeBridge:
        def retrieve_news_context(self, *, query, limit=10, filters=None):
            calls.append(query)
            return [retrieved_item]

    monkeypatch.setattr("jarvis.generation.services.retrieval_bridge.RetrievalBridge", lambda: _FakeBridge())

    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Central bank raised the rate (РўРђРЎРЎ)."),
        config=GenerationConfig(enable_logging=False),
        chat_service=_FakeChatService(),
    )

    result = service.generate_chat_answer(
        db_session=object(),
        user_query="central bank rate",
        news_items=[
            _make_news_item(
                news_id=801,
                source_name="РўРђРЎРЎ",
                title="Football match",
                content="The team won the match.",
            )
        ],
        user_id=1,
        rag_mode_override="self_rag",
    )

    assert calls == ["central bank rate"]
    assert result.rag_mode == "self_rag"
    assert result.sources[0].news_id == 802
