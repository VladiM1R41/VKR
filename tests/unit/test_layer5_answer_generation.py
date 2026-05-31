from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

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
from jarvis.generation.services.providers.base import LLMProviderError


def test_generation_config_reads_llm_token_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.answer_generation_service as generation_module

    monkeypatch.setattr(
        generation_module,
        "get_settings",
        lambda: SimpleNamespace(
            jarvis_llm_max_input_tokens=100000,
            jarvis_llm_max_output_tokens=0,
            jarvis_llm_digest_max_output_tokens=0,
            jarvis_llm_temperature=0.25,
        ),
    )

    config = GenerationConfig.from_settings()

    assert config.max_input_tokens == 100000
    assert config.max_output_tokens is None
    assert config.digest_max_output_tokens is None
    assert config.temperature == 0.25


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


class _CaptureCache:
    def __init__(self) -> None:
        self.get_calls: list[dict] = []
        self.set_calls: list[dict] = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return None

    def set(self, **kwargs) -> None:
        self.set_calls.append(kwargs)


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
    url: str = "https://example.test/news",
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
        url=url,
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


def test_generate_answer_keeps_current_query_separate_from_chat_memory() -> None:
    provider = _SequenceProvider(["AI will change developer work [Doc 1]."])
    service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=False, enable_correction=False),
    )
    cache = _CaptureCache()
    service._response_cache = cache

    service.generate_answer(
        user_query="Will AI replace programmers?",
        conversation_context="Previous messages:\nAssistant: Aviation restrictions were introduced.",
        news_items=[
            _make_news_item(
                news_id=901,
                source_name="CNews",
                title="AI and developers",
                content="AI tools automate routine coding tasks, while developers remain responsible for design.",
            )
        ],
        intent="FACTUAL",
    )

    request = provider.requests[0]
    assert request.user_prompt.startswith("Will AI replace programmers?")
    assert "Previous messages:" in request.user_prompt
    assert request.user_prompt.index("Will AI replace programmers?") < request.user_prompt.index("Previous messages:")
    assert cache.get_calls[0]["query"] == "Will AI replace programmers?"
    assert cache.set_calls[0]["query"] == "Will AI replace programmers?"


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
    assert captured["entry"].documents_used[0]["url"] == "https://example.test/news"
    assert captured["entry"].documents_used[0]["published_at"] == "2026-04-15"
    assert captured["entry"].documents_used[-1]["meta"]["generation_mode"] == "digest"


def test_generate_digest_uses_digest_output_token_budget() -> None:
    provider = _SequenceProvider(["Digest text (TASS)."])
    service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=False, digest_max_output_tokens=3333),
    )

    service.generate_digest(
        news_items=[
            _make_news_item(
                news_id=503,
                source_name="TASS",
                title="Main event",
                content="Main event happened today.",
                personalized_score=0.95,
                event_cluster_id=13,
            )
        ],
        user_id=1,
    )

    assert provider.requests[0].max_output_tokens == 3333


def test_generate_digest_adds_digest_style_instruction() -> None:
    provider = _SequenceProvider(["Digest text (TASS)."])
    service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=False),
    )

    service.generate_digest(
        news_items=[
            _make_news_item(
                news_id=504,
                source_name="TASS",
                title="Main event",
                content="Main event happened today.",
                personalized_score=0.95,
                event_cluster_id=14,
            )
        ],
        user_id=1,
        digest_style="editorial",
    )

    assert "редакторский" in provider.requests[0].user_prompt
    assert provider.requests[0].user_prompt.startswith("Составь большой новостной дайджест")


def test_digest_correction_prompt_keeps_sources_in_metadata() -> None:
    provider = _SequenceProvider(
        [
            "Martians built a bridge without evidence.",
            "Событие дня подтверждено источником.",
        ]
    )
    service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=False),
    )

    service.generate_digest(
        news_items=[
            _make_news_item(
                news_id=505,
                source_name="TASS",
                title="Main event",
                content="Main event happened today.",
                personalized_score=0.95,
                event_cluster_id=15,
            )
        ],
        user_id=1,
    )

    assert len(provider.requests) == 2
    assert "не добавляй блок «Источники»" in provider.requests[1].user_prompt
    assert "[Doc N]" in provider.requests[1].user_prompt
    assert "Интерфейс покажет использованные статьи" in provider.requests[1].user_prompt


def test_generate_digest_raises_when_provider_refuses() -> None:
    refusal = (
        "Генеративные языковые модели не обладают собственным мнением — их ответы являются "
        "обобщением информации, находящейся в открытом доступе. Чтобы избежать ошибок и "
        "неправильного толкования, разговоры на некоторые темы временно ограничены."
    )
    service = AnswerGenerationService(
        provider=_AsyncFakeProvider(refusal),
        config=GenerationConfig(enable_logging=False, enable_correction=False),
    )

    with pytest.raises(LLMProviderError):
        service.generate_digest(
            news_items=[
                _make_news_item(
                    news_id=506,
                    source_name="CNews",
                    title="ИИ помогает компаниям искать персональные данные",
                    content="Компании начали применять ИИ для поиска неучтенных персональных данных в архивах.",
                    personalized_score=0.95,
                    event_cluster_id=16,
                )
            ],
            user_id=1,
        )


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

    assert result.citation_valid is True
    assert result.has_unsupported_claims is True
    assert result.confidence == "LOW"
    assert captured["entry"].confidence == "LOW"
    assert "Источники:" not in result.digest_text
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
        self.user_messages: list[str] = []
        self.assistant_messages: list[str] = []

    def get_or_create_session(self, db_session, *, user_id, session_id=None, title=None):
        return _FakeChatSession()

    def save_user_message(self, db_session, *, session_id, content):
        self.user_messages.append(content)
        return None

    def save_assistant_message(self, db_session, *, session_id, content, generation_log_id=None):
        self.assistant_messages.append(content)
        return None

    def update_session_title(self, db_session, *, session_id, title):
        return None


def test_generate_chat_answer_builds_memory_before_saving_current_question() -> None:
    provider = _SequenceProvider(["AI will change developer work [Doc 1]."])
    chat_service = _FakeChatService()

    class _FakeMemoryService:
        def refresh_summary_if_needed(self, db_session, session_id):
            return ""

        def build_memory_block(self, db_session, session_id):
            assert chat_service.user_messages == []
            return "Previous messages:\nAssistant: Aviation restrictions were introduced."

    service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=False, enable_correction=False),
        chat_service=chat_service,
        chat_memory_service=_FakeMemoryService(),
    )
    service._response_cache = _NoCache()

    service.generate_chat_answer(
        db_session=object(),
        user_query="Will AI replace programmers?",
        news_items=[
            _make_news_item(
                news_id=902,
                source_name="CNews",
                title="AI and developers",
                content="AI tools automate routine coding tasks, while developers remain responsible for design.",
            )
        ],
        user_id=1,
    )

    assert chat_service.user_messages == ["Will AI replace programmers?"]
    assert provider.requests[0].user_prompt.startswith("Will AI replace programmers?")
    assert "Previous messages:" in provider.requests[0].user_prompt


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
