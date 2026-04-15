"""Pydantic models for Layer 5 chat operations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageEntry(BaseModel):
    """Одно сообщение из истории чата."""
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    created_at: datetime | None = None
    generation_log_id: int | None = None


class ChatSessionInfo(BaseModel):
    """Информация о сессии чата."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime


class ChatRequest(BaseModel):
    """Запрос на генерацию ответа в чате."""
    model_config = ConfigDict(protected_namespaces=())

    query: str
    user_id: int
    session_id: int | None = None
    session_title: str | None = None
    limit: int = 10  # top-K документов из retrieval


class ChatResponse(BaseModel):
    """Ответ чата."""
    model_config = ConfigDict(protected_namespaces=())

    session_id: int
    message_id: int
    answer: str
    rag_mode: str
    model_name: str
    confidence: str | None
    sources: list[dict[str, object]] = Field(default_factory=list)
    generation_log_id: int | None = None
    latency_ms: int
