"""Standard RAG generation service — Шаг 4+5 реализации Слоя 5.

Архитектура (по FINAL_LAYER_5_GUIDE.md, разделы 9-12, 18.1-18.3):
  Слой 5 отвечает за переход от персонализированного набора релевантных документов
  к связному ответу, дайджесту или аналитическому обзору.

  Pipeline Standard RAG:
    1. Принять shortlist документов (из Слоя 3 или Слоя 4).
    2. Собрать контекст (context_assembler).
    3. Построить промпт (prompt_builder).
    4. Вызвать LLM-провайдер (LLMProvider).
    5. Сохранить generation_log (generation_logger).
    6. Вернуть ответ с metadata.
    7. (Шаг 5) Сохранить user/assistant сообщения в chat_messages.

  Режимы генерации (раздел 9):
    - factual: краткий точный ответ
    - capability: объяснение смысла и последствий
    - intent: аналитика, осторожный прогноз
    - digest: связный дайджест из нескольких источников
    - alert: короткое push-уведомление

  Principles (раздел 3):
    - Retrieval-augmented, не LLM-first
    - Groundedness важнее красоты
    - Generation after selection
    - Выводы первыми (для analytical/digest)
    - Generation и critique разделяем (Шаг 6)
    - Chat persistence: каждое сообщение сохраняется в БД (Шаг 5)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.generation.services.chat_service import ChatService

from jarvis.generation.services.chat_memory_service import ChatMemoryService
from jarvis.generation.services.citation_validator import CitationValidationResult, CitationValidator
from jarvis.generation.services.confidence_service import compute_confidence as compute_confidence_label
from jarvis.generation.services.hallucination_checker import GroundednessResult, HallucinationChecker
from jarvis.generation.services.context_assembler import (
    AssembledContext,
    NewsWithContext,
    assemble_context_for_chat,
    assemble_context_for_digest,
)
from jarvis.generation.services.generation_logger import (
    GenerationLogEntry,
    GenerationLogResult,
    save_generation_log,
)
from jarvis.generation.services.prompt_builder import (
    DocumentContext,
    GenerationMode,
    PromptResult,
    build_prompt,
    estimate_token_count,
    intent_to_mode,
)
from jarvis.generation.services.response_cache import ResponseCache
from jarvis.generation.services.providers.base import (
    LLMProvider,
    LLMGenerationRequest,
    LLMGenerationResponse,
)

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────
# Data-классы: вход/выход сервиса
# ───────────────────────────────────────────────────────────

# Версия промпта (инкрементируется при изменении шаблонов)
_PROMPT_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Информация об использованном источнике."""
    news_id: int
    source_name: str
    title: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class GenerationAnswerResult:
    """Результат генерации ответа."""
    answer_text: str                    # сгенерированный текст
    rag_mode: str                       # использованный режим
    model_name: str                     # модель-провайдер
    confidence: str | None              # "LOW"/"MEDIUM"/"HIGH"/"TOP"
    sources: list[SourceInfo]           # использованные источники
    documents_used_count: int           # сколько документов подано в LLM
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int                     # полная латентность (включая сборку)
    generation_log_id: int | None       # ID записи в generation_logs
    assembled_context: AssembledContext  # собранный контекст (для отладки)
    # Шаг 6: проверка качества
    citation_valid: bool = True         # все цитаты валидны
    groundedness_score: float = 1.0     # 0.0-1.0 groundedness
    has_unsupported_claims: bool = False  # есть неподтверждённые claims


@dataclass(frozen=True, slots=True)
class GenerationDigestResult:
    """Результат генерации дайджеста."""
    digest_text: str                    # сгенерированный текст дайджеста
    rag_mode: str                       # "digest"
    model_name: str
    confidence: str | None
    sources: list[SourceInfo]
    documents_used_count: int
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    generation_log_id: int | None
    n_event_clusters: int               # сколько событийных кластеров в дайджесте
    assembled_context: AssembledContext
    # Шаг 6: проверка качества
    citation_valid: bool = True
    groundedness_score: float = 1.0
    has_unsupported_claims: bool = False


@dataclass
class GenerationConfig:
    """Конфигурация генерации (переопределяет дефолты)."""
    max_input_tokens: int = 20000       # лимит входного контекста
    max_output_tokens: int = 1200       # лимит ответа
    temperature: float = 0.2            # низкая для groundedness
    enable_logging: bool = True         # сохранять ли в generation_logs
    enable_correction: bool = True      # one extra LLM pass for failed quality checks
    correction_groundedness_threshold: float = 0.45


# ───────────────────────────────────────────────────────────
# Confidence service (MVP — rule-based, раздел 11.2)
# ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class QualityCheckResult:
    """Post-generation quality signals shared by answer/digest/alert modes."""

    confidence: str
    citation_valid: bool
    groundedness_score: float
    has_unsupported_claims: bool
    recommendation: str


@dataclass(frozen=True, slots=True)
class CorrectionOutcome:
    response: LLMGenerationResponse
    quality: QualityCheckResult
    attempted: bool
    applied: bool
    reason: str | None = None


def _legacy_compute_confidence(
    n_documents: int,
    avg_trust_score: float,
    avg_content_grade: float,
    has_conflicting_sources: bool = False,
) -> str:
    """Вычислить системную оценку надёжности ответа (confidence label).

    По FINAL_LAYER_5_GUIDE.md раздел 11.2:
      confidence label НЕ равен "уверенности LLM в себе".
      Это системная оценка надёжности ответа по контексту.

    Источники для confidence:
      - число независимых документов
      - их trust / content grade
      - наличие противоречий
      - согласованность по event cluster

    MVP-мэппинг:
      TOP:    3+ документов, trust >= 0.8, grade <= 2, без противоречий
      HIGH:   2+ документов, trust >= 0.6, grade <= 3
      MEDIUM: 1+ документов, trust >= 0.4, grade <= 4
      LOW:    иначе (слабые источники, мало подтверждений)
    """
    if n_documents == 0:
        return "LOW"

    # Критерий TOP
    if (n_documents >= 3
            and avg_trust_score >= 0.8
            and avg_content_grade <= 2
            and not has_conflicting_sources):
        return "TOP"

    # Критерий HIGH
    if (n_documents >= 2
            and avg_trust_score >= 0.6
            and avg_content_grade <= 3):
        return "HIGH"

    # Критерий MEDIUM
    if (n_documents >= 1
            and avg_trust_score >= 0.4
            and avg_content_grade <= 4):
        return "MEDIUM"

    return "LOW"


# ───────────────────────────────────────────────────────────
# Главный сервис: Standard RAG
# ───────────────────────────────────────────────────────────

class AnswerGenerationService:
    """Standard RAG generation — оркестратор генерации ответов.

    Принимает shortlist документов, собирает контекст, строит промпт,
    вызывает LLM-провайдер, сохраняет generation_log, возвращает ответ.

    Если передан chat_service — также сохраняет user/assistant сообщения.

    Usage (без чата):
        service = AnswerGenerationService(provider=..., config=...)
        result = service.generate_answer(
            user_query="Что с ключевой ставкой?",
            news_items=[...],         # list[NewsWithContext]
            user_id=1,
            intent="FACTUAL",         # из Слоя 3
        )

    Usage (с чатом):
        from jarvis.db.session import SyncSessionLocal
        from jarvis.generation.services.chat_service import ChatService

        chat_service = ChatService()
        service = AnswerGenerationService(provider=..., config=..., chat_service=chat_service)
        with SyncSessionLocal() as db:
            result = service.generate_chat_answer(
                db=db,
                user_query="Что с ключевой ставкой?",
                news_items=[...],
                user_id=1,
                session_id=None,  # создаст новую
                intent="FACTUAL",
            )
    """

    def __init__(
        self,
        provider: LLMProvider,
        config: GenerationConfig | None = None,
        chat_service: ChatService | None = None,
        chat_memory_service: ChatMemoryService | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or GenerationConfig()
        self._chat_service = chat_service
        self._chat_memory_service = chat_memory_service
        self._response_cache = ResponseCache()

    # ───────────────────────────────────────────────────────
    # Chat answer generation (раздел 18.1)
    # ───────────────────────────────────────────────────────

    def generate_answer(
        self,
        *,
        user_query: str,
        news_items: list[NewsWithContext],
        user_id: int | None = None,
        intent: str = "FACTUAL",
        conversation_context: str = "",
        rag_mode_override: str = "standard",
    ) -> GenerationAnswerResult:
        """Сгенерировать grounded-ответ на запрос пользователя.

        Pipeline:
          1. Определить режим из intent.
          2. Собрать контекст (assemble_context_for_chat).
          3. Построить промпт (build_prompt).
          4. Вызвать LLM-провайдер.
          5. Сохранить generation_log.
          6. Вернуть ответ.

        Args:
            user_query: запрос пользователя.
            news_items: shortlist документов (из Слоя 3 или 4).
            user_id: опциональный ID пользователя для логирования.
            intent: классификация из Слоя 3 (FACTUAL/CAPABILITY/INTENT).

        Returns:
            GenerationAnswerResult с ответом, metadata и sources.
        """
        t_start = time.monotonic()

        # Шаг 1: определить режим
        mode = intent_to_mode(intent)
        prompt_query = user_query
        if conversation_context:
            prompt_query = f"{conversation_context}\n\nТекущий вопрос пользователя:\n{user_query}"

        # Шаг 2: собрать контекст
        assembled = assemble_context_for_chat(
            news_items=news_items,
            max_input_tokens=self._config.max_input_tokens,
            system_prompt=self._get_system_prompt(mode),
            user_query=prompt_query,
        )

        # Шаг 3: построить промпт
        system_prompt = self._get_system_prompt(mode)
        prompt = build_prompt(
            mode=mode,
            user_query=prompt_query,
            documents=assembled.documents,
        )

        cache_doc_ids = [doc.news_id for doc in assembled.documents if doc.news_id is not None]
        provider_key, model_key = self._provider_cache_identity()
        cached = self._response_cache.get(
            mode=mode,
            rag_mode=rag_mode_override,
            query=prompt_query,
            document_ids=cache_doc_ids,
            prompt_version=_PROMPT_VERSION,
            provider_key=provider_key,
            model_key=model_key,
        )
        if cached:
            latency_ms = int((time.monotonic() - t_start) * 1000)
            generation_log_id = self._save_generation_log_safely(
                user_id=user_id,
                query=user_query,
                rag_mode=rag_mode_override,
                model_name=str(cached["model_name"]),
                input_tokens=cached.get("input_tokens"),
                output_tokens=cached.get("output_tokens"),
                latency_ms=latency_ms,
                confidence=cached.get("confidence"),
                documents=assembled.documents,
                answer_text=str(cached["answer_text"]),
                context={"cache_hit": True},
            )
            return GenerationAnswerResult(
                answer_text=str(cached["answer_text"]),
                rag_mode=str(cached.get("rag_mode", rag_mode_override)),
                model_name=str(cached["model_name"]),
                confidence=cached.get("confidence"),
                sources=self._extract_sources(news_items, assembled.documents),
                documents_used_count=len(assembled.documents),
                input_tokens=cached.get("input_tokens"),
                output_tokens=cached.get("output_tokens"),
                latency_ms=latency_ms,
                generation_log_id=generation_log_id,
                assembled_context=assembled,
                citation_valid=bool(cached.get("citation_valid", True)),
                groundedness_score=float(cached.get("groundedness_score", 1.0)),
                has_unsupported_claims=bool(cached.get("has_unsupported_claims", False)),
            )

        # Шаг 4: вызвать LLM-провайдер
        llm_response = self._call_provider(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            context=prompt.context_block,
            mode=mode,
        )

        # Шаг 5: вычислить confidence
        confidence = self._compute_confidence_from_items(news_items, assembled.documents)
        quality = self._evaluate_generation_quality(
            answer_text=llm_response.content,
            documents=assembled.documents,
            base_confidence=confidence,
        )
        correction = self._maybe_correct_generation(
            response=llm_response,
            quality=quality,
            documents=assembled.documents,
            mode=mode,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            context=prompt.context_block,
            base_confidence=confidence,
        )
        llm_response = correction.response
        quality = correction.quality

        # Шаг 6: собрать sources
        sources = self._extract_sources(news_items, assembled.documents)

        # Шаг 6 (дополнительно): citation + groundedness check
        latency_ms = int((time.monotonic() - t_start) * 1000)

        # Шаг 7: сохранить generation_log
        generation_log_id = self._save_generation_log_safely(
            user_id=user_id,
            query=user_query,
            rag_mode=rag_mode_override,
            model_name=llm_response.model_name,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            latency_ms=latency_ms,
            confidence=quality.confidence,
            documents=assembled.documents,
            answer_text=llm_response.content,
            context={
                "cache_hit": False,
                "citation_valid": quality.citation_valid,
                "groundedness_score": quality.groundedness_score,
                "quality_recommendation": quality.recommendation,
                "correction_attempted": correction.attempted,
                "correction_applied": correction.applied,
                "correction_reason": correction.reason,
            },
        )

        result = GenerationAnswerResult(
            answer_text=llm_response.content,
            rag_mode=rag_mode_override,
            model_name=llm_response.model_name,
            confidence=quality.confidence,
            sources=sources,
            documents_used_count=len(assembled.documents),
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            latency_ms=latency_ms,
            generation_log_id=generation_log_id,
            assembled_context=assembled,
            citation_valid=quality.citation_valid,
            groundedness_score=quality.groundedness_score,
            has_unsupported_claims=quality.has_unsupported_claims,
        )
        self._response_cache.set(
            mode=mode,
            rag_mode=rag_mode_override,
            query=prompt_query,
            document_ids=cache_doc_ids,
            prompt_version=_PROMPT_VERSION,
            provider_key=provider_key,
            model_key=model_key,
            result={
                "answer_text": result.answer_text,
                "rag_mode": result.rag_mode,
                "model_name": result.model_name,
                "confidence": result.confidence,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "citation_valid": result.citation_valid,
                "groundedness_score": result.groundedness_score,
                "has_unsupported_claims": result.has_unsupported_claims,
                "correction_applied": correction.applied,
            },
        )
        return result

    # ───────────────────────────────────────────────────────
    # Chat answer generation с persistence (Шаг 5)
    # ───────────────────────────────────────────────────────

    def generate_chat_answer(
        self,
        db_session,
        *,
        user_query: str,
        news_items: list[NewsWithContext],
        user_id: int,
        session_id: int | None = None,
        session_title: str | None = None,
        intent: str = "FACTUAL",
        rag_mode_override: str = "standard",
    ) -> GenerationAnswerResult:
        """Сгенерировать ответ и сохранить в чат-сессии.

        Pipeline:
          1. Получить/создать chat_session.
          2. Сохранить user message.
          3. Вызвать generate_answer.
          4. Сохранить assistant message с generation_log_id.
          5. Обновить заголовок сессии из первого вопроса (если новый).

        Args:
            db_session: SQLAlchemy Session (обязательно передан извне).
            user_query: запрос пользователя.
            news_items: shortlist документов.
            user_id: ID пользователя.
            session_id: существующая сессия или None для новой.
            session_title: заголовок новой сессии (опционально).
            intent: классификация из Слоя 3.

        Returns:
            GenerationAnswerResult с добавленным created_session_id.
        """
        if self._chat_service is None:
            raise RuntimeError(
                "ChatService не передан в AnswerGenerationService. "
                "Создайте сервис с chat_service=ChatService()."
            )

        # 1. Получить или создать сессию
        was_new_session = session_id is None
        chat_session = self._chat_service.get_or_create_session(
            db_session,
            user_id=user_id,
            session_id=session_id,
            title=session_title,
        )

        # 2. Сохранить сообщение пользователя
        self._chat_service.save_user_message(
            db_session,
            session_id=chat_session.id,
            content=user_query,
        )

        # 3. Сгенерировать ответ (диспетчер RAG-режимов)
        conversation_context = ""
        if self._chat_memory_service is not None:
            self._chat_memory_service.refresh_summary_if_needed(db_session, chat_session.id)
            conversation_context = self._chat_memory_service.build_memory_block(
                db_session,
                chat_session.id,
            )

        retrieval_fn = None
        if rag_mode_override in {"crag", "self_rag"}:
            from jarvis.generation.services.retrieval_bridge import RetrievalBridge

            retrieval_bridge = RetrievalBridge()
            retrieval_limit = max(10, len(news_items))

            def retrieval_fn(query: str) -> list[NewsWithContext]:
                return retrieval_bridge.retrieve_news_context(query=query, limit=retrieval_limit)

        if rag_mode_override == "crag":
            from jarvis.generation.services.rag_modes.crag import CRAGService
            crag_service = CRAGService()
            crag_result = crag_service.generate(
                answer_service=self,
                user_query=user_query,
                news_items=news_items,
                retrieval_fn=retrieval_fn,
                user_id=user_id,
                intent=intent,
                conversation_context=conversation_context,
            )
            result = crag_result.answer
        elif rag_mode_override == "self_rag":
            from jarvis.generation.services.rag_modes.self_rag_light import SelfRAGLightService
            self_rag_service = SelfRAGLightService()
            self_rag_result = self_rag_service.generate(
                answer_service=self,
                user_query=user_query,
                news_items=news_items,
                retrieval_fn=retrieval_fn,
                user_id=user_id,
                intent=intent,
                conversation_context=conversation_context,
            )
            result = self_rag_result.answer
        elif rag_mode_override == "graph_rag":
            from jarvis.generation.services.rag_modes.graph_rag_light import GraphRAGLightService

            graph_rag_service = GraphRAGLightService()
            graph_rag_result = graph_rag_service.generate(
                session=db_session,
                answer_service=self,
                user_query=user_query,
                news_items=news_items,
                user_id=user_id,
                intent=intent,
            )
            result = graph_rag_result.answer
        else:
            result = self.generate_answer(
                user_query=user_query,
                news_items=news_items,
                user_id=user_id,
                intent=intent,
                conversation_context=conversation_context,
                rag_mode_override=rag_mode_override,
            )

        # 4. Сохранить ответ ассистента
        if result.generation_log_id is not None:
            self._chat_service.save_assistant_message(
                db_session,
                session_id=chat_session.id,
                content=result.answer_text,
                generation_log_id=result.generation_log_id,
            )
        else:
            # Даже без generation_log_id сохраняем ответ
            self._chat_service.save_assistant_message(
                db_session,
                session_id=chat_session.id,
                content=result.answer_text,
            )

        # 5. Обновить заголовок если сессия новая
        if was_new_session and session_title is None:
            # Берём первые 50 символов вопроса как заголовок
            auto_title = user_query[:50] + ("..." if len(user_query) > 50 else "")
            self._chat_service.update_session_title(
                db_session,
                session_id=chat_session.id,
                title=auto_title,
            )

        return result

    # ───────────────────────────────────────────────────────
    # Digest generation (раздел 18.2)
    # ───────────────────────────────────────────────────────

    def generate_digest(
        self,
        *,
        news_items: list[NewsWithContext],
        user_id: int | None = None,
        continuity_context: str = "",
    ) -> GenerationDigestResult:
        """Сгенерировать текст дайджеста из shortlist (из Слоя 4).

        Pipeline:
          1. Собрать контекст (assemble_context_for_digest — с кластеризацией).
          2. Построить промпт (mode=digest).
          3. Вызвать LLM-провайдер.
          4. Сохранить generation_log.
          5. Вернуть текст дайджеста.

        Args:
            news_items: shortlist из Слоя 4 (DigestOrchestrationService).
            user_id: опциональный ID пользователя.
            continuity_context: контекст предыдущих дайджестов (опционально).

        Returns:
            GenerationDigestResult с текстом дайджеста и metadata.
        """
        t_start = time.monotonic()
        mode: GenerationMode = "digest"

        # Шаг 1: собрать контекст (с кластеризацией по event_cluster_id)
        assembled = assemble_context_for_digest(
            news_items=news_items,
            max_input_tokens=self._config.max_input_tokens,
            system_prompt=self._get_system_prompt(mode),
        )

        # Шаг 2: построить промпт
        system_prompt = self._get_system_prompt(mode)
        user_query = ""
        if continuity_context:
            user_query = (
                f"Учти также, что в предыдущих дайджестах было:\n{continuity_context}\n\n"
            )
        user_query += f"Составь дайджест из {len(assembled.documents)} источников ниже."

        prompt = build_prompt(
            mode=mode,
            user_query=user_query,
            documents=assembled.documents,
        )

        # Шаг 3: вызвать LLM-провайдер
        llm_response = self._call_provider(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            context=prompt.context_block,
            mode=mode,
        )

        # Шаг 4: confidence
        confidence = self._compute_confidence_from_items(news_items, assembled.documents)

        # Шаг 5: sources
        sources = self._extract_sources(news_items, assembled.documents)

        latency_ms = int((time.monotonic() - t_start) * 1000)

        # Шаг 6: сохранить generation_log
        quality = self._evaluate_generation_quality(
            answer_text=llm_response.content,
            documents=assembled.documents,
            base_confidence=confidence,
        )
        correction = self._maybe_correct_generation(
            response=llm_response,
            quality=quality,
            documents=assembled.documents,
            mode=mode,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            context=prompt.context_block,
            base_confidence=confidence,
        )
        llm_response = correction.response
        quality = correction.quality
        latency_ms = int((time.monotonic() - t_start) * 1000)

        generation_log_id = self._save_generation_log_safely(
            user_id=user_id,
            query="digest generation",
            rag_mode="standard",
            model_name=llm_response.model_name,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            latency_ms=latency_ms,
            confidence=quality.confidence,
            documents=assembled.documents,
            answer_text=llm_response.content,
            context={
                "generation_mode": "digest",
                "citation_valid": quality.citation_valid,
                "groundedness_score": quality.groundedness_score,
                "quality_recommendation": quality.recommendation,
                "n_event_clusters": assembled.n_clusters,
                "correction_attempted": correction.attempted,
                "correction_applied": correction.applied,
                "correction_reason": correction.reason,
            },
        )

        return GenerationDigestResult(
            digest_text=llm_response.content,
            rag_mode="digest",
            model_name=llm_response.model_name,
            confidence=quality.confidence,
            sources=sources,
            documents_used_count=len(assembled.documents),
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            latency_ms=latency_ms,
            generation_log_id=generation_log_id,
            n_event_clusters=assembled.n_clusters,
            assembled_context=assembled,
            citation_valid=quality.citation_valid,
            groundedness_score=quality.groundedness_score,
            has_unsupported_claims=quality.has_unsupported_claims,
        )

    # ───────────────────────────────────────────────────────
    # Alert text generation (раздел 18.3)
    # ───────────────────────────────────────────────────────

    def generate_alert(
        self,
        *,
        news_item: NewsWithContext,
        alert_reason: str,
        user_id: int | None = None,
    ) -> GenerationAnswerResult:
        """Сгенерировать короткий alert-текст.

        Alert text: короткий, быстрый, grounded, без длинной аналитики.
        """
        t_start = time.monotonic()
        mode: GenerationMode = "alert"

        assembled = assemble_context_for_chat(
            news_items=[news_item],
            max_input_tokens=self._config.max_input_tokens,
            system_prompt=self._get_system_prompt(mode),
            user_query=alert_reason,
        )

        prompt = build_prompt(
            mode=mode,
            user_query=alert_reason,
            documents=assembled.documents,
        )

        llm_response = self._call_provider(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            context=prompt.context_block,
            mode=mode,
        )

        latency_ms = int((time.monotonic() - t_start) * 1000)
        sources = [SourceInfo(
            news_id=news_item.news_id,
            source_name=news_item.source_name,
            title=news_item.title,
        )]
        confidence = self._compute_confidence_from_items([news_item], assembled.documents)
        quality = self._evaluate_generation_quality(
            answer_text=llm_response.content,
            documents=assembled.documents,
            base_confidence=confidence,
        )
        correction = self._maybe_correct_generation(
            response=llm_response,
            quality=quality,
            documents=assembled.documents,
            mode=mode,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            context=prompt.context_block,
            base_confidence=confidence,
        )
        llm_response = correction.response
        quality = correction.quality
        latency_ms = int((time.monotonic() - t_start) * 1000)

        generation_log_id = self._save_generation_log_safely(
            user_id=user_id,
            query=f"alert: {alert_reason}",
            rag_mode="standard",
            model_name=llm_response.model_name,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            latency_ms=latency_ms,
            confidence=quality.confidence,
            documents=assembled.documents,
            answer_text=llm_response.content,
            context={
                "generation_mode": "alert",
                "citation_valid": quality.citation_valid,
                "groundedness_score": quality.groundedness_score,
                "quality_recommendation": quality.recommendation,
                "correction_attempted": correction.attempted,
                "correction_applied": correction.applied,
                "correction_reason": correction.reason,
            },
        )

        return GenerationAnswerResult(
            answer_text=llm_response.content,
            rag_mode="alert",
            model_name=llm_response.model_name,
            confidence=quality.confidence,
            sources=sources,
            documents_used_count=1,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            latency_ms=latency_ms,
            generation_log_id=generation_log_id,
            assembled_context=assembled,
            citation_valid=quality.citation_valid,
            groundedness_score=quality.groundedness_score,
            has_unsupported_claims=quality.has_unsupported_claims,
        )

    # ───────────────────────────────────────────────────────
    # Internal helpers
    # ───────────────────────────────────────────────────────

    def _call_provider(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: str,
        mode: GenerationMode,
    ) -> LLMGenerationResponse:
        """Вызвать LLM-провайдер с собранным промптом."""
        request = LLMGenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context=context,
            max_output_tokens=self._config.max_output_tokens,
            temperature=self._config.temperature,
            metadata={"mode": mode, "prompt_version": _PROMPT_VERSION},
        )
        result = self._provider.generate(request)
        if not inspect.isawaitable(result):
            return result

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(result)

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, result).result()

    def _provider_cache_identity(self) -> tuple[str, str]:
        """Return stable provider/model identity for response cache keys."""
        providers = getattr(self._provider, "_providers", None)
        if providers:
            provider_key = ">".join(str(provider.provider_name) for provider in providers)
            model_key = ">".join(str(provider.config.model_name) for provider in providers)
            return provider_key, model_key

        provider_name = str(getattr(self._provider, "provider_name", "unknown"))
        config = getattr(self._provider, "config", None)
        model_name = str(getattr(config, "model_name", "unknown"))
        return provider_name, model_name

    def _save_generation_log_safely(
        self,
        *,
        user_id: int | None,
        query: str | None,
        rag_mode: str,
        model_name: str,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int | None,
        confidence: str | None,
        documents: list[DocumentContext],
        answer_text: str,
        context: dict | None = None,
    ) -> int | None:
        """Persist generation trace if logging is enabled.

        Logging stays non-fatal for user-facing generation, but cache hits are
        logged too so ablation/debug history does not disappear.
        """
        if not self._config.enable_logging:
            return None

        documents_used = [
            {"news_id": doc.news_id, "source": doc.source_name, "title": doc.title}
            for doc in documents
        ]
        if context:
            documents_used.append({"meta": context})

        log_entry = GenerationLogEntry(
            user_id=user_id,
            query=query,
            rag_mode=rag_mode,
            model_name=model_name,
            prompt_version=_PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            confidence=confidence,
            documents_used=documents_used,
            answer_text=answer_text,
        )
        try:
            log_result = save_generation_log(log_entry)
            return log_result.log_id
        except Exception:
            logger.exception("Failed to save generation log (non-fatal)")
            return None

    def _get_system_prompt(self, mode: GenerationMode) -> str:
        """Получить системный промпт для режима."""
        from jarvis.generation.services.prompt_builder import _MODE_SYSTEM
        return _MODE_SYSTEM[mode]

    def _evaluate_generation_quality(
        self,
        *,
        answer_text: str,
        documents: list[DocumentContext],
        base_confidence: str,
    ) -> QualityCheckResult:
        citation_result = self._validate_citations(answer_text, documents)
        groundedness_result = self._check_groundedness(answer_text, documents)
        citation_valid = citation_result.is_valid and (
            citation_result.total_citations > 0 or not documents
        )

        confidence = base_confidence
        if not citation_valid or not groundedness_result.is_acceptable:
            confidence = self._cap_confidence(confidence, "MEDIUM")
        if groundedness_result.overall_score < 0.45:
            confidence = self._cap_confidence(confidence, "LOW")

        return QualityCheckResult(
            confidence=confidence,
            citation_valid=citation_valid,
            groundedness_score=groundedness_result.overall_score,
            has_unsupported_claims=not groundedness_result.is_acceptable,
            recommendation=groundedness_result.recommendation,
        )

    def _maybe_correct_generation(
        self,
        *,
        response: LLMGenerationResponse,
        quality: QualityCheckResult,
        documents: list[DocumentContext],
        mode: GenerationMode,
        system_prompt: str,
        user_prompt: str,
        context: str,
        base_confidence: str,
    ) -> CorrectionOutcome:
        """Retry once with a correction prompt when quality checks fail."""
        if not self._config.enable_correction:
            return CorrectionOutcome(
                response=response,
                quality=quality,
                attempted=False,
                applied=False,
                reason="disabled",
            )
        if not documents:
            return CorrectionOutcome(
                response=response,
                quality=quality,
                attempted=False,
                applied=False,
                reason="no_documents",
            )
        if not self._needs_correction(quality):
            return CorrectionOutcome(
                response=response,
                quality=quality,
                attempted=False,
                applied=False,
                reason="quality_ok",
            )

        correction_prompt = self._build_correction_prompt(
            user_prompt=user_prompt,
            answer_text=response.content,
            quality=quality,
        )
        try:
            corrected_response = self._call_provider(
                system_prompt=system_prompt,
                user_prompt=correction_prompt,
                context=context,
                mode=mode,
            )
        except Exception:
            logger.exception("Correction generation failed; keeping original answer")
            return CorrectionOutcome(
                response=response,
                quality=quality,
                attempted=True,
                applied=False,
                reason="provider_error",
            )

        corrected_quality = self._evaluate_generation_quality(
            answer_text=corrected_response.content,
            documents=documents,
            base_confidence=base_confidence,
        )
        if self._is_quality_improved(corrected_quality, quality):
            return CorrectionOutcome(
                response=corrected_response,
                quality=corrected_quality,
                attempted=True,
                applied=True,
                reason="quality_improved",
            )
        return CorrectionOutcome(
            response=response,
            quality=quality,
            attempted=True,
            applied=False,
            reason="not_improved",
        )

    def _needs_correction(self, quality: QualityCheckResult) -> bool:
        return (
            not quality.citation_valid
            or quality.has_unsupported_claims
            or quality.groundedness_score < self._config.correction_groundedness_threshold
        )

    @staticmethod
    def _build_correction_prompt(
        *,
        user_prompt: str,
        answer_text: str,
        quality: QualityCheckResult,
    ) -> str:
        return (
            "Исправь предыдущий ответ по правилам строгого RAG.\n"
            "Используй только факты из блока CONTEXT. Удали все неподтвержденные утверждения. "
            "Каждое важное утверждение снабжай ссылкой на документ в формате [Doc N] "
            "или (Источник, [Doc N]). Если данных недостаточно, скажи это явно.\n\n"
            f"Причина исправления: citation_valid={quality.citation_valid}, "
            f"groundedness_score={quality.groundedness_score}, "
            f"recommendation={quality.recommendation}.\n\n"
            f"Исходный пользовательский запрос:\n{user_prompt}\n\n"
            f"Предыдущий ответ:\n{answer_text}\n\n"
            "Верни только исправленный ответ без служебных комментариев."
        )

    @staticmethod
    def _is_quality_improved(
        corrected: QualityCheckResult,
        original: QualityCheckResult,
    ) -> bool:
        rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "TOP": 3}
        corrected_score = (
            int(corrected.citation_valid),
            int(not corrected.has_unsupported_claims),
            corrected.groundedness_score,
            rank.get(corrected.confidence, 0),
        )
        original_score = (
            int(original.citation_valid),
            int(not original.has_unsupported_claims),
            original.groundedness_score,
            rank.get(original.confidence, 0),
        )
        return corrected_score > original_score

    @staticmethod
    def _cap_confidence(value: str, max_value: str) -> str:
        rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "TOP": 3}
        labels = {score: label for label, score in rank.items()}
        return labels[min(rank.get(value or "LOW", 0), rank[max_value])]

    def _compute_confidence_from_items(
        self,
        news_items: list[NewsWithContext],
        used_documents: list[DocumentContext],
    ) -> str:
        """Вычислить confidence на основе использованных документов."""
        if not used_documents:
            return "LOW"

        # Собираем trust_score и content_grade из news_items
        used_news_ids = {doc.news_id for doc in used_documents if doc.news_id is not None}
        trust_scores: list[float] = []
        content_grades: list[float] = []
        for item in news_items:
            # Проверяем, что этот документ использован (по index)
            if used_news_ids and item.news_id not in used_news_ids:
                continue
            trust_scores.append(item.trust_score)
            content_grades.append(item.content_grade)

        avg_trust = sum(trust_scores) / len(trust_scores) if trust_scores else 0.5
        avg_grade = sum(content_grades) / len(content_grades) if content_grades else 6.0

        # Проверяем conflicting sources: если в кластере есть источники
        # с разными content_type или противоречивой информацией
        has_conflicts = False  # TODO: реализовать в Шаге 6

        return compute_confidence_label(
            n_documents=len(used_documents),
            avg_trust_score=avg_trust,
            avg_content_grade=avg_grade,
            has_conflicting_sources=has_conflicts,
        )

    def _extract_sources(
        self,
        news_items: list[NewsWithContext],
        used_documents: list[DocumentContext],
    ) -> list[SourceInfo]:
        """Извлечь список использованных источников."""
        sources_map: dict[int, SourceInfo] = {}
        for item in news_items:
            sources_map[item.news_id] = SourceInfo(
                news_id=item.news_id,
                source_name=item.source_name,
                title=item.title,
            )

        # Возвращаем только те, что реально использованы
        seen_news_ids: set[int] = set()
        # doc.index = i+1 из assemble_context, но news_id хранится в news_items
        # Для MVP маппим по порядку
        result: list[SourceInfo] = []
        for doc in used_documents:
            if doc.news_id is None or doc.news_id in seen_news_ids:
                continue
            item = sources_map.get(doc.news_id)
            if item is None:
                continue
            result.append(item)
            seen_news_ids.add(doc.news_id)
        return result

    # ───────────────────────────────────────────────────────
    # Шаг 6: Citation & Groundedness checks
    # ───────────────────────────────────────────────────────

    def _validate_citations(
        self,
        answer_text: str,
        documents: list[DocumentContext],
    ) -> CitationValidationResult:
        """Проверить что источники в ответе соответствуют документам из контекста."""
        validator = CitationValidator()
        docs_for_check = [
            {"index": doc.index, "source": doc.source_name, "news_id": doc.news_id}
            for doc in documents
        ]
        return validator.validate(answer_text, docs_for_check)

    def _check_groundedness(
        self,
        answer_text: str,
        documents: list[DocumentContext],
    ) -> GroundednessResult:
        """Проверить что ответ grounded на предоставленных документах."""
        checker = HallucinationChecker()
        docs_for_check = [
            {
                "news_id": doc.news_id,
                "source": doc.source_name,
                "content": doc.content,
                "title": doc.title,
            }
            for doc in documents
        ]
        return checker.check_groundedness(answer_text, docs_for_check)


# ───────────────────────────────────────────────────────────
# Factory: создать сервис с провайдером из настроек
# ───────────────────────────────────────────────────────────

def build_answer_generation_service(
    provider: LLMProvider | None = None,
    config: GenerationConfig | None = None,
    chat_service: ChatService | None = None,
    chat_memory_service: ChatMemoryService | None = None,
) -> AnswerGenerationService:
    """Создать AnswerGenerationService с провайдером из factory.

    Если provider не передан — создаётся через build_primary_provider().
    chat_service опционален — если передан, будет работать chat persistence.
    """
    if provider is None:
        from jarvis.generation.services.providers.factory import (
            build_primary_provider,
        )
        provider = build_primary_provider()

    return AnswerGenerationService(
        provider=provider,
        config=config,
        chat_service=chat_service,
        chat_memory_service=chat_memory_service,
    )
