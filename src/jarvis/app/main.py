"""FastAPI приложение «Джарвис» — Слой 6: API & Interfaces.

Точка входа:
    uvicorn src.jarvis.app.main:app --reload --port 8000

Swagger UI:
    http://localhost:8000/docs

Single-user режим: все запросы от user_id=1.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jarvis.core.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте, очистка при остановке."""
    logger.info("Jarvis API starting up...")

    # Seed пользователя по умолчанию (single-user режим)
    from jarvis.app.dependencies import seed_default_user
    try:
        seed_default_user()
    except Exception as exc:
        logger.warning("seed_default_user failed (БД может быть недоступна): %s", exc)

    logger.info("Jarvis API ready.")
    yield
    logger.info("Jarvis API shutting down.")


app = FastAPI(
    title="Jarvis News Assistant API",
    version="1.0.0",
    description="""
## Персонализированная новостная система «Джарвис»

**RAG = IR + LLM**: гибридный поиск (BM25 + dense embeddings) с генерацией ответов через LLM.

### Слои системы

| Слой | Компонент | Технологии |
|------|-----------|-----------|
| 1 | Data Ingestion | RSS → PostgreSQL |
| 2 | Processing | Natasha NER, BGE-M3, Qdrant |
| 3 | Hybrid Retrieval | dense+sparse RRF, cross-encoder reranking |
| 4 | Personalization | EMA-профили, anti-filter-bubble |
| 5 | RAG Generation | GigaChat/YandexGPT, CRAG, Self-RAG, GraphRAG |
| 6 | API (этот слой) | FastAPI, Swagger UI |

### Режим запуска

**Single-user**: все запросы от пользователя с `user_id=1`.
Аутентификация не требуется.
""",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS — разрешаем всё для локальной разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Роутеры ──────────────────────────────────────────────────────────────────

from jarvis.app.api.v1.health import router as health_router
from jarvis.app.api.v1.search import router as search_router
from jarvis.app.api.v1.chat import router as chat_router
from jarvis.app.api.v1.digest import router as digest_router
from jarvis.app.api.v1.sources import router as sources_router
from jarvis.app.api.v1.profile import router as profile_router
from jarvis.app.api.v1.feedback import router as feedback_router
from jarvis.app.api.v1.news import router as news_router
from jarvis.app.api.v1.entities import router as entities_router
from jarvis.app.api.v1.analytics import router as analytics_router

# Health — без префикса /api/v1 (liveness/readiness probes)
app.include_router(health_router)

# API v1
API_PREFIX = "/api/v1"
app.include_router(search_router, prefix=API_PREFIX)
app.include_router(chat_router, prefix=API_PREFIX)
app.include_router(digest_router, prefix=API_PREFIX)
app.include_router(sources_router, prefix=API_PREFIX)
app.include_router(profile_router, prefix=API_PREFIX)
app.include_router(feedback_router, prefix=API_PREFIX)
app.include_router(news_router, prefix=API_PREFIX)
app.include_router(entities_router, prefix=API_PREFIX)
app.include_router(analytics_router, prefix=API_PREFIX)
