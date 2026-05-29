"""Celery tasks for Layer 5 generation."""

from __future__ import annotations

import asyncio
import logging

from jarvis.core.logging import log_event
from jarvis.db.session import SyncSessionLocal
from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationConfig,
)
from jarvis.generation.services.chat_memory_service import ChatMemoryService
from jarvis.generation.services.chat_service import ChatService
from jarvis.generation.services.context_assembler import NewsWithContext
from jarvis.generation.services.providers.factory import build_primary_provider
from jarvis.ingestion.tasks.celery_app import celery_app


logger = logging.getLogger(__name__)


def _build_service() -> AnswerGenerationService:
    """Создать AnswerGenerationService с ChatService."""
    provider = build_primary_provider()
    chat_service = ChatService()
    chat_memory_service = ChatMemoryService(chat_service=chat_service)
    return AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(),
        chat_service=chat_service,
        chat_memory_service=chat_memory_service,
    )


async def _run_chat_answer(
    *,
    user_query: str,
    news_items_data: list[dict],
    user_id: int,
    session_id: int | None = None,
    intent: str = "FACTUAL",
) -> dict:
    """Асинхронная обёртка для генерации ответа с сохранением в чат."""
    service = _build_service()

    # Восстанавливаем NewsWithContext из dict
    news_items = [
        NewsWithContext(
            news_id=item["news_id"],
            source_id=item.get("source_id", 0),
            source_name=item["source_name"],
            title=item["title"],
            content=item.get("content", ""),
            snippet_lead=item.get("snippet_lead") or item.get("snippet"),
            score=item.get("score", 0.0),
            rerank_score=item.get("rerank_score"),
            personalized_score=item.get("personalized_score"),
            topics=item.get("topics", []),
            entities=item.get("entities", []),
            published_at_str=item.get("published_at_str") or item.get("published_at", ""),
            trust_score=item.get("trust_score", 0.5),
            content_grade=item.get("content_grade", 6),
            information_type=item.get("information_type", "daily"),
            urgency=item.get("urgency", "normal"),
            event_cluster_id=item.get("event_cluster_id"),
            url=item.get("url", ""),
        )
        for item in news_items_data
    ]

    with SyncSessionLocal() as db:
        result = service.generate_chat_answer(
            db_session=db,
            user_query=user_query,
            news_items=news_items,
            user_id=user_id,
            session_id=session_id,
            intent=intent,
        )
        db.commit()

        return {
            "status": "success",
            "answer_text": result.answer_text,
            "rag_mode": result.rag_mode,
            "model_name": result.model_name,
            "confidence": result.confidence,
            "sources": [
                {
                    "news_id": s.news_id,
                    "source_name": s.source_name,
                    "title": s.title,
                    "url": s.url,
                }
                for s in result.sources
            ],
            "generation_log_id": result.generation_log_id,
            "latency_ms": result.latency_ms,
        }


@celery_app.task(
    name="jarvis.generation.generate_chat_answer",
    queue="generation_queue",
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
    time_limit=120,
    soft_time_limit=100,
)
def generate_chat_answer_task(
    user_query: str,
    news_items_data: list[dict],
    user_id: int,
    session_id: int | None = None,
    intent: str = "FACTUAL",
) -> dict:
    """Celery task: генерация ответа с сохранением в чат-сессию.

    Args:
        user_query: запрос пользователя.
        news_items_data: список документов в формате dict для сериализации.
        user_id: ID пользователя.
        session_id: ID существующей чат-сессии или None для новой.
        intent: FACTUAL/CAPABILITY/INTENT.

    Returns:
        dict с результатом генации или error.
    """
    try:
        return asyncio.run(
            _run_chat_answer(
                user_query=user_query,
                news_items_data=news_items_data,
                user_id=user_id,
                session_id=session_id,
                intent=intent,
            )
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "generation_chat_failed",
            user_id=user_id,
            session_id=session_id,
            error=str(exc),
        )
        return {
            "status": "error",
            "error": str(exc),
            "user_id": user_id,
            "session_id": session_id,
        }
