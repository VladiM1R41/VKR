"""POST /chat, WS /ws/chat — диалоговый RAG-интерфейс."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from jarvis.app.dependencies import get_db, get_default_user_id
from jarvis.db.models import ChatMessage, ChatSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ChatIn(BaseModel):
    message: str
    session_id: Optional[str] = None
    mode: str = "standard"  # standard | crag | self_rag | graph_rag


class SourceCitation(BaseModel):
    news_id: int
    title: str
    source_name: str
    url: Optional[str] = None
    published_at: Optional[datetime] = None


class ChatOut(BaseModel):
    session_id: str
    message_id: Optional[int] = None
    answer: str
    confidence: str
    sources: list[SourceCitation]
    generation_log_id: Optional[int] = None
    rag_mode: str


class ChatSessionOut(BaseModel):
    session_id: str
    title: Optional[str]
    message_count: int
    last_message_at: Optional[datetime]
    created_at: datetime


class ChatSessionsOut(BaseModel):
    items: list[ChatSessionOut]
    total: int


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    generation_log_id: Optional[int]


class ChatMessagesOut(BaseModel):
    session_id: str
    messages: list[ChatMessageOut]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ChatOut,
    summary="Задать вопрос Джарвису (RAG-чат)",
    description="Принимает вопрос, выполняет поиск релевантных новостей (L3→L4), "
                "генерирует ответ через выбранный RAG-режим (L5) и возвращает "
                "текст с цитированием источников.",
)
def chat(
    body: ChatIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> ChatOut:
    from jarvis.generation.services import AnswerGenerationService, ChatService, GenerationConfig
    from jarvis.generation.services.providers.factory import build_primary_provider
    from jarvis.personalization.services.ranking_service import PersonalizedRankingService
    from jarvis.retrieval.models.search_models import SearchRequest
    from jarvis.retrieval.services.search_service import SearchService
    from jarvis.generation.services.context_assembler import enrich_with_db_data

    # L3: поиск
    search_service = SearchService()
    ranking_service = PersonalizedRankingService()
    l3_response = search_service.search(SearchRequest(query=body.message, limit=10))
    l4_response = ranking_service.rerank(db, user_id=user_id, response=l3_response)

    # Контекст для LLM
    news_ids = [r.news_id for r in l4_response.results[:5]]
    source_ids = {r.source_id for r in l4_response.results[:5]}
    titles = {r.news_id: r.title for r in l4_response.results[:5]}
    snippets = {r.news_id: r.snippet for r in l4_response.results[:5]}
    scores = {r.news_id: r.base_score for r in l4_response.results[:5]}
    rerank_scores = {r.news_id: r.rerank_score for r in l4_response.results[:5]}
    personalized_scores = {r.news_id: r.personalized_score for r in l4_response.results[:5]}
    topics_map = {r.news_id: r.topics for r in l4_response.results[:5]}
    entities_map = {r.news_id: r.entities for r in l4_response.results[:5]}
    published_map = {
        r.news_id: r.published_at.isoformat() if r.published_at else ""
        for r in l4_response.results[:5]
    }
    trust_map = {r.news_id: 0.7 for r in l4_response.results[:5]}
    grade_map = {r.news_id: 3 for r in l4_response.results[:5]}

    docs = enrich_with_db_data(
        news_ids=news_ids,
        source_ids=source_ids,
        titles=titles,
        snippets=snippets,
        scores=scores,
        rerank_scores={k: v or 0.0 for k, v in rerank_scores.items()},
        personalized_scores=personalized_scores,
        topics_map=topics_map,
        entities_map=entities_map,
        published_map=published_map,
        trust_map=trust_map,
        grade_map=grade_map,
        info_type_map={r.news_id: "daily" for r in l4_response.results[:5]},
        urgency_map={r.news_id: "normal" for r in l4_response.results[:5]},
        cluster_map={r.news_id: None for r in l4_response.results[:5]},
    )

    # L5: генерация
    provider = build_primary_provider()
    chat_service = ChatService()
    gen_service = AnswerGenerationService(provider=provider, config=GenerationConfig(), chat_service=chat_service)

    session_id_int = int(body.session_id) if body.session_id else None
    session_obj = chat_service.get_or_create_session(db, user_id=user_id, session_id=session_id_int)

    result = gen_service.generate_chat_answer(
        db,
        user_query=body.message,
        news_items=docs,
        user_id=user_id,
        session_id=int(session_obj.id),
        rag_mode_override=body.mode,
    )

    msg = chat_service.save_assistant_message(
        db,
        session_id=int(session_obj.id),
        content=result.answer_text,
        generation_log_id=result.generation_log_id,
    )

    sources = [
        SourceCitation(
            news_id=s.news_id,
            title=s.title,
            source_name=s.source_name,
            url=s.url,
        )
        for s in result.sources
    ]
    return ChatOut(
        session_id=str(session_obj.id),
        message_id=msg.message_id if msg else None,
        answer=result.answer_text,
        confidence=result.confidence,
        sources=sources,
        generation_log_id=result.generation_log_id,
        rag_mode=body.mode,
    )


@router.get(
    "/sessions",
    response_model=ChatSessionsOut,
    summary="История чат-сессий",
)
def list_sessions(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> ChatSessionsOut:
    total = db.scalar(
        select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id)
    ) or 0
    rows = db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.last_message_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        ChatSessionOut(
            session_id=str(r.id),
            title=r.title,
            message_count=db.scalar(
                select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == r.id)
            ) or 0,
            last_message_at=r.last_message_at,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return ChatSessionsOut(items=items, total=int(total))


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatMessagesOut,
    summary="Сообщения чат-сессии",
)
def session_messages(
    session_id: str,
    db: Session = Depends(get_db),
) -> ChatMessagesOut:
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == int(session_id))
        .order_by(ChatMessage.created_at.asc())
    ).all()
    messages = [
        ChatMessageOut(
            id=int(r.id),
            role=str(r.role),
            content=str(r.content),
            created_at=r.created_at,
            generation_log_id=r.generation_log_id,
        )
        for r in rows
    ]
    return ChatMessagesOut(session_id=session_id, messages=messages)


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def chat_ws(websocket: WebSocket):
    """WebSocket: стриминговый RAG-чат.

    Client sends: {"message": "...", "session_id": "...", "mode": "standard"}
    Server streams tokens: {"type": "token", "content": "..."}
    Server sends done:     {"type": "done", "session_id": "...", "confidence": "HIGH", "sources": [...]}
    """
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON"})
                continue

            message = data.get("message", "").strip()
            if not message:
                await websocket.send_json({"type": "error", "detail": "Empty message"})
                continue

            session_id = data.get("session_id")
            mode = data.get("mode", "standard")

            # Запуск генерации в отдельном потоке (синхронные сервисы)
            await websocket.send_json({"type": "thinking"})
            try:
                result = await asyncio.to_thread(
                    _ws_generate,
                    message=message,
                    session_id=session_id,
                    mode=mode,
                    user_id=1,
                )
                # Эмулируем стриминг: разбиваем ответ на слова
                words = result["answer"].split()
                for word in words:
                    await websocket.send_json({"type": "token", "content": word + " "})
                    await asyncio.sleep(0.02)
                await websocket.send_json({
                    "type": "done",
                    "session_id": result["session_id"],
                    "confidence": result["confidence"],
                    "sources": result["sources"],
                    "rag_mode": mode,
                })
            except Exception as exc:
                logger.exception("WS chat generation error: %s", exc)
                await websocket.send_json({"type": "error", "detail": str(exc)})

    except WebSocketDisconnect:
        pass


DEFAULT_USER_ID_WS = 1


def _ws_generate(*, message: str, session_id: str | None, mode: str, user_id: int) -> dict:
    """Синхронная обёртка для запуска в asyncio.to_thread."""
    from jarvis.db.session import SyncSessionLocal
    from jarvis.generation.services import AnswerGenerationService, ChatService, GenerationConfig
    from jarvis.generation.services.context_assembler import enrich_with_db_data
    from jarvis.generation.services.providers.factory import build_primary_provider
    from jarvis.personalization.services.ranking_service import PersonalizedRankingService
    from jarvis.retrieval.models.search_models import SearchRequest
    from jarvis.retrieval.services.search_service import SearchService

    search_service = SearchService()
    l3_response = search_service.search(SearchRequest(query=message, limit=10))

    with SyncSessionLocal() as db:
        ranking_service = PersonalizedRankingService()
        l4_response = ranking_service.rerank(db, user_id=user_id, response=l3_response)

        top = l4_response.results[:5]
        docs = enrich_with_db_data(
            news_ids=[r.news_id for r in top],
            source_ids={r.source_id for r in top},
            titles={r.news_id: r.title for r in top},
            snippets={r.news_id: r.snippet for r in top},
            scores={r.news_id: r.base_score for r in top},
            rerank_scores={r.news_id: r.rerank_score or 0.0 for r in top},
            personalized_scores={r.news_id: r.personalized_score for r in top},
            topics_map={r.news_id: r.topics for r in top},
            entities_map={r.news_id: r.entities for r in top},
            published_map={r.news_id: r.published_at.isoformat() if r.published_at else "" for r in top},
            trust_map={r.news_id: 0.7 for r in top},
            grade_map={r.news_id: 3 for r in top},
            info_type_map={r.news_id: "daily" for r in top},
            urgency_map={r.news_id: "normal" for r in top},
            cluster_map={r.news_id: None for r in top},
        )

        provider = build_primary_provider()
        chat_service = ChatService()
        gen_service = AnswerGenerationService(provider=provider, config=GenerationConfig(), chat_service=chat_service)

        session_id_int = int(session_id) if session_id else None
        session_obj = chat_service.get_or_create_session(db, user_id=user_id, session_id=session_id_int)

        result = gen_service.generate_chat_answer(
            db,
            user_query=message,
            news_items=docs,
            user_id=user_id,
            session_id=int(session_obj.id),
            rag_mode_override=mode,
        )
        chat_service.save_assistant_message(
            db,
            session_id=int(session_obj.id),
            content=result.answer_text,
            generation_log_id=result.generation_log_id,
        )

        return {
            "session_id": str(session_obj.id),
            "answer": result.answer_text,
            "confidence": result.confidence,
            "sources": [
                {"news_id": s.news_id, "title": s.title, "source_name": s.source_name}
                for s in result.sources
            ],
        }
