"""Generation logger для Слоя 5 — сохранение GenerationLog в PostgreSQL.

Архитектура (по FINAL_LAYER_5_GUIDE.md, раздел 14.3):
  generation_logs — одна из ключевых таблиц исследовательской части проекта.
  Позволяет ответить на вопросы:
    - какой rag_mode использовался
    - какая модель отвечала
    - какая версия prompt была активна
    - сколько токенов ушло
    - сколько длилась генерация
    - какие документы использовались
    - какой текст был сгенерирован
    - какой confidence был присвоен

  generation_logs храним бессрочно — это база для ablation study и воспроизводимости.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from jarvis.db.models import GenerationLog
from jarvis.db.session import SyncSessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GenerationLogEntry:
    """Структурированная запись для логирования генерации."""
    user_id: int | None
    query: str | None
    rag_mode: str                    # "standard", "crag", "self_rag", "graph_rag", "agentic"
    model_name: str                  # например "gigachat-max"
    prompt_version: str              # например "v1"
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    confidence: str | None           # "LOW", "MEDIUM", "HIGH", "TOP"
    documents_used: list[dict]       # [{"news_id": 1, "source": "ТАСС", ...}, ...]
    answer_text: str


@dataclass(frozen=True, slots=True)
class GenerationLogResult:
    """Результат сохранения generation log."""
    log_id: int
    entry: GenerationLogEntry


def save_generation_log(entry: GenerationLogEntry) -> GenerationLogResult:
    """Сохранить запись генерации в generation_logs.

    Args:
        entry: структурированная запись генерации.

    Returns:
        GenerationLogResult с ID сохранённой записи.

    Raises:
        SQLAlchemyError при проблемах с БД (caller должен обработать).
    """
    log_record = GenerationLog(
        user_id=entry.user_id,
        query=entry.query,
        rag_mode=entry.rag_mode,
        model_name=entry.model_name,
        prompt_version=entry.prompt_version,
        input_tokens=entry.input_tokens,
        output_tokens=entry.output_tokens,
        latency_ms=entry.latency_ms,
        confidence=entry.confidence,
        documents_used=entry.documents_used,
        answer_text=entry.answer_text,
    )

    with SyncSessionLocal() as session:
        session.add(log_record)
        session.flush()
        log_id = log_record.id
        session.commit()

    logger.info(
        "Generation log saved: id=%d, rag_mode=%s, model=%s, tokens=%d/%d, latency=%dms",
        log_id, entry.rag_mode, entry.model_name,
        entry.input_tokens or 0, entry.output_tokens or 0,
        entry.latency_ms or 0,
    )

    return GenerationLogResult(log_id=log_id, entry=entry)


def get_generation_log_by_id(log_id: int) -> GenerationLog | None:
    """Получить запись генерации по ID.

    Используется для связывания chat_messages с generation_logs.
    """
    with SyncSessionLocal() as session:
        return session.get(GenerationLog, log_id)


def get_generation_logs_for_user(
    user_id: int,
    limit: int = 50,
    rag_mode: str | None = None,
) -> list[GenerationLog]:
    """Получить последние записи генерации для пользователя.

    Используется для ablation study и анализа истории генераций.
    """
    with SyncSessionLocal() as session:
        stmt = select(GenerationLog).where(
            GenerationLog.user_id == user_id
        ).order_by(GenerationLog.created_at.desc()).limit(limit)

        if rag_mode:
            stmt = stmt.where(GenerationLog.rag_mode == rag_mode)

        return session.scalars(stmt).all()
