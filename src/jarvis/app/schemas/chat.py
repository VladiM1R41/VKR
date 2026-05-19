"""Chat API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: int | None = None
    mode: str = Field("standard", pattern="^(standard|crag|self_rag|graph_rag)$")
    limit: int = Field(8, ge=1, le=20)


class ChatSource(BaseModel):
    news_id: int
    source_name: str
    title: str


class ChatResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    session_id: int | None = None
    answer: str
    confidence: str
    rag_mode: str
    model_name: str
    generation_log_id: int | None = None
    search_time_ms: float | None = None
    sources: list[ChatSource]
    citation_valid: bool = True
    groundedness_score: float = 1.0
    has_unsupported_claims: bool = False


class ChatSessionItem(BaseModel):
    id: int
    title: str | None = None
    created_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0


class ChatSessionsResponse(BaseModel):
    items: list[ChatSessionItem]


class ChatMessageItem(BaseModel):
    id: int
    role: str
    content: str
    generation_log_id: int | None = None
    created_at: datetime


class ChatMessagesResponse(BaseModel):
    session_id: int
    messages: list[ChatMessageItem]
