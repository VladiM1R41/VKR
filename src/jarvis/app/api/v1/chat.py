"""Chat endpoints over retrieval, personalization and Layer 5 generation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.chat import (
    ChatMessageItem,
    ChatMessagesResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionItem,
    ChatSessionsResponse,
    ChatSource,
)
from jarvis.db.models import ChatMessage, ChatSession, News
from jarvis.generation.services.answer_generation_service import build_answer_generation_service
from jarvis.generation.services.chat_memory_service import ChatMemoryService
from jarvis.generation.services.chat_service import ChatService
from jarvis.generation.services.context_assembler import NewsWithContext
from jarvis.personalization.models.ranking_models import PersonalizedResult
from jarvis.personalization.services.pipeline_service import PersonalizationPipelineService
from jarvis.retrieval.models.search_models import SearchRequest
from jarvis.retrieval.services.search_service import SearchService

router = APIRouter()


def _personalized_context(session: Session, results: list[PersonalizedResult]) -> list[NewsWithContext]:
    news_ids = [item.news_id for item in results]
    if not news_ids:
        return []
    rows = session.scalars(select(News).where(News.id.in_(news_ids))).all()
    news_by_id = {row.id: row for row in rows}
    context: list[NewsWithContext] = []
    for item in results:
        news = news_by_id.get(item.news_id)
        if news is None:
            continue
        context.append(
            NewsWithContext(
                news_id=item.news_id,
                source_id=item.source_id,
                source_name=item.source_name,
                title=item.title,
                content=news.content,
                snippet_lead=news.snippet_lead or item.snippet,
                score=float(item.base_score),
                rerank_score=item.rerank_score,
                personalized_score=float(item.personalized_score),
                topics=list(item.topics),
                entities=list(item.entities),
                published_at_str=str(item.published_at or news.published_at or ""),
                trust_score=float(item.trust_score),
                content_grade=int(item.content_grade),
                information_type=item.information_type,
                urgency=item.urgency,
                event_cluster_id=item.event_cluster_id,
            )
        )
    return context


def _search_context(session: Session, *, query: str, limit: int, user_id: int):
    l3_response = SearchService().search(SearchRequest(query=query, limit=limit), user_id=str(user_id))
    l4_response = PersonalizationPipelineService().personalize(session, user_id=user_id, response=l3_response)
    return l3_response, l4_response, _personalized_context(session, l4_response.results)


@router.get("/sessions", response_model=ChatSessionsResponse)
def list_sessions(
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    limit: int = 30,
) -> ChatSessionsResponse:
    rows = ChatService().list_user_sessions(session, user_id=user_id, limit=limit)
    counts = dict(
        session.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_([row.id for row in rows] or [-1]))
            .group_by(ChatMessage.session_id)
        ).all()
    )
    return ChatSessionsResponse(
        items=[
            ChatSessionItem(
                id=row.id,
                title=row.title,
                created_at=row.created_at,
                last_message_at=row.last_message_at,
                message_count=int(counts.get(row.id, 0)),
            )
            for row in rows
        ]
    )


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesResponse)
def get_messages(
    session_id: int,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ChatMessagesResponse:
    chat_session = ChatService().get_session(session, session_id=session_id, user_id=user_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    rows = session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    ).all()
    return ChatMessagesResponse(
        session_id=session_id,
        messages=[
            ChatMessageItem(
                id=row.id,
                role=row.role,
                content=row.content,
                generation_log_id=row.generation_log_id,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ChatResponse:
    l3_response, _, context = _search_context(session, query=request.message, limit=request.limit, user_id=user_id)
    if not context:
        raise HTTPException(status_code=404, detail="No processed news context found for this question")

    service = build_answer_generation_service(
        chat_service=ChatService(),
        chat_memory_service=ChatMemoryService(),
    )
    try:
        result = service.generate_chat_answer(
            session,
            user_query=request.message,
            news_items=context,
            user_id=user_id,
            session_id=request.session_id,
            intent=l3_response.intent,
            rag_mode_override=request.mode,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}") from exc

    chat_session_id = request.session_id
    if chat_session_id is None:
        latest = session.scalar(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(desc(ChatSession.last_message_at).nullslast(), desc(ChatSession.id))
            .limit(1)
        )
        chat_session_id = latest.id if latest else None

    return ChatResponse(
        session_id=chat_session_id,
        answer=result.answer_text,
        confidence=result.confidence or "LOW",
        rag_mode=result.rag_mode,
        model_name=result.model_name,
        generation_log_id=result.generation_log_id,
        search_time_ms=l3_response.search_time_ms,
        sources=[
            ChatSource(news_id=source.news_id, source_name=source.source_name, title=source.title)
            for source in result.sources
        ],
        citation_valid=result.citation_valid,
        groundedness_score=result.groundedness_score,
        has_unsupported_claims=result.has_unsupported_claims,
    )


@router.websocket("/ws")
async def chat_ws(websocket: WebSocket) -> None:
    """Simple WebSocket wrapper: generate a full answer, then stream words."""
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        request = ChatRequest.model_validate(payload)
        from jarvis.db.session import SyncSessionLocal

        with SyncSessionLocal() as db:
            response = chat(request, db, get_current_user_id())
        for token in response.answer.split():
            await websocket.send_json({"type": "token", "content": token + " "})
        await websocket.send_json({"type": "done", "payload": response.model_dump(mode="json")})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})
    finally:
        await websocket.close()

