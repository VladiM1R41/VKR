"""Admin API schemas."""

from __future__ import annotations

from typing import Any
from datetime import datetime

from pydantic import BaseModel, Field


class AdminOverviewResponse(BaseModel):
    corpus: dict[str, int]
    infrastructure: dict[str, str]
    recent_errors: list[dict] = Field(default_factory=list)


class AdminSourceItem(BaseModel):
    id: int
    name: str
    type: str
    is_active: bool
    health_status: str
    consecutive_failures: int
    parse_success_rate: float | None = None
    extraction_success_rate: float | None = None
    last_crawled: datetime | None = None
    last_error: str | None = None


class AdminSourcesResponse(BaseModel):
    items: list[AdminSourceItem]


class AdminProcessingResponse(BaseModel):
    processed: int
    unprocessed: int
    chunks: int
    qdrant: dict


class AdminSearchStatsResponse(BaseModel):
    total_searches: int
    avg_latency_ms: float | None
    cache_hit_count: int
    retrieval_modes: dict[str, int]
    recent_queries: list[dict]


class AdminGenerationStatsResponse(BaseModel):
    total_generations: int
    avg_latency_ms: float | None
    rag_modes: dict[str, int]
    confidence: dict[str, int]
    recent_generations: list[dict]


class AdminUserItem(BaseModel):
    id: int
    username: str
    email: str | None = None
    is_admin: bool
    has_password: bool
    created_at: datetime
    last_active_at: datetime | None = None
    chat_sessions: int = 0
    interactions: int = 0
    digests: int = 0
    search_logs: int = 0
    generation_logs: int = 0


class AdminUsersResponse(BaseModel):
    items: list[AdminUserItem]
    total: int
    admin_count: int


class AdminUserUpdateRequest(BaseModel):
    is_admin: bool | None = None


class AdminSettingsResponse(BaseModel):
    auth: dict[str, Any]
    runtime: dict[str, Any]
    retrieval: dict[str, Any]
    llm: dict[str, Any]
    celery: dict[str, Any]
