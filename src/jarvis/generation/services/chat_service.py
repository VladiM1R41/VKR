"""Chat session and message management service for Layer 5.

Отвечает за:
- создание/получение chat_sessions
- сохранение user/assistant сообщений в chat_messages
- загрузку sliding window истории для контекста LLM
- связывание assistant message с generation_log_id
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from jarvis.core.logging import log_event
from jarvis.db.models import ChatMessage, ChatSession


logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────
# Data-классы
# ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ChatHistoryEntry:
    """Одна запись из истории чата."""
    role: str           # 'user' | 'assistant'
    content: str
    created_at: datetime | None
    generation_log_id: int | None


@dataclass(frozen=True, slots=True)
class ChatWindow:
    """Окно истории чата для контекста LLM."""
    session_id: int
    entries: list[ChatHistoryEntry]
    total_messages: int


@dataclass(frozen=True, slots=True)
class SavedMessageResult:
    """Результат сохранения сообщения."""
    message_id: int
    session_id: int
    role: str
    generation_log_id: int | None


# ───────────────────────────────────────────────────────────
# Константы
# ───────────────────────────────────────────────────────────

DEFAULT_WINDOW_SIZE = 5          # последних пар user/assistant
DEFAULT_MAX_HISTORY = 20         # максимум загружаемых сообщений


class ChatService:
    """Управление диалоговыми сессиями и сообщениями.

    Usage:
        chat_service = ChatService()
        with SyncSessionLocal() as db:
            session_obj = chat_service.get_or_create(db, user_id=1)
            chat_service.save_user_message(db, session_obj.id, "Привет!")
            chat_service.save_assistant_message(db, session_obj.id, "Ответ...", generation_log_id=42)
            window = chat_service.load_chat_window(db, session_obj.id)
    """

    def __init__(
        self,
        *,
        window_size: int = DEFAULT_WINDOW_SIZE,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        self._window_size = window_size
        self._max_history = max_history

    # ───────────────────────────────────────────────────────
    # Сессии
    # ───────────────────────────────────────────────────────

    def create_session(
        self,
        session: Session,
        user_id: int,
        title: str | None = None,
    ) -> ChatSession:
        """Создать новую диалоговую сессию."""
        now = datetime.now(timezone.utc)
        chat_session = ChatSession(
            user_id=user_id,
            title=title,
            created_at=now,
            last_message_at=now,
        )
        session.add(chat_session)
        session.flush()
        log_event(
            logger,
            logging.INFO,
            "chat_session_created",
            session_id=chat_session.id,
            user_id=user_id,
        )
        return chat_session

    def get_session(
        self,
        session: Session,
        session_id: int,
        user_id: int,
    ) -> ChatSession | None:
        """Получить сессию, проверяя принадлежность пользователю."""
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
        return session.scalar(stmt)

    def get_or_create_session(
        self,
        session: Session,
        user_id: int,
        session_id: int | None = None,
        title: str | None = None,
    ) -> ChatSession:
        """Получить существующую сессию или создать новую."""
        if session_id is not None:
            existing = self.get_session(session, session_id, user_id)
            if existing is not None:
                return existing

        return self.create_session(session, user_id, title=title)

    def list_user_sessions(
        self,
        session: Session,
        user_id: int,
        limit: int = 20,
    ) -> list[ChatSession]:
        """Список сессий пользователя, от новых к старым."""
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.last_message_at.desc().nulls_last(), ChatSession.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    def update_session_title(self, session: Session, session_id: int, title: str) -> bool:
        """Обновить заголовок сессии. Возвращает True если успешно."""
        chat_session = session.get(ChatSession, session_id)
        if chat_session is None:
            return False
        chat_session.title = title
        session.flush()
        return True

    def delete_session(self, session: Session, session_id: int, user_id: int) -> bool:
        """Удалить сессию (и все сообщения через CASCADE)."""
        chat_session = self.get_session(session, session_id, user_id)
        if chat_session is None:
            return False
        session.delete(chat_session)
        session.flush()
        log_event(
            logger,
            logging.INFO,
            "chat_session_deleted",
            session_id=session_id,
            user_id=user_id,
        )
        return True

    # ───────────────────────────────────────────────────────
    # Сообщения
    # ───────────────────────────────────────────────────────

    def save_user_message(
        self,
        session: Session,
        session_id: int,
        content: str,
    ) -> SavedMessageResult:
        """Сохранить сообщение пользователя."""
        msg = ChatMessage(
            session_id=session_id,
            role="user",
            content=content,
        )
        session.add(msg)
        session.flush()
        self._touch_session(session, session_id)

        log_event(
            logger,
            logging.DEBUG,
            "chat_user_message_saved",
            session_id=session_id,
            message_id=msg.id,
        )
        return SavedMessageResult(
            message_id=msg.id,
            session_id=session_id,
            role="user",
            generation_log_id=None,
        )

    def save_assistant_message(
        self,
        session: Session,
        session_id: int,
        content: str,
        generation_log_id: int | None = None,
    ) -> SavedMessageResult:
        """Сохранить ответ ассистента, связывая с generation_log.

        generation_log_id — опциональный FK на generation_logs.
        Позволяет воспроизвести ответ по логу генерации.
        """
        msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=content,
            generation_log_id=generation_log_id,
        )
        session.add(msg)
        session.flush()
        self._touch_session(session, session_id)

        log_event(
            logger,
            logging.DEBUG,
            "chat_assistant_message_saved",
            session_id=session_id,
            message_id=msg.id,
            generation_log_id=generation_log_id,
        )
        return SavedMessageResult(
            message_id=msg.id,
            session_id=session_id,
            role="assistant",
            generation_log_id=generation_log_id,
        )

    # ───────────────────────────────────────────────────────
    # Sliding window для контекста LLM
    # ───────────────────────────────────────────────────────

    def load_chat_window(
        self,
        session: Session,
        session_id: int,
        window_size: int | None = None,
    ) -> ChatWindow:
        """Загрузить окно последних сообщений для контекста LLM.

        Загружает последние N сообщений (window_size пар user+assistant).
        Возвращает сообщения в хронологическом порядке (старые → новые).
        """
        effective_window = window_size or self._window_size
        max_entries = max(self._max_history, effective_window * 2)

        # Загружаем с конца (новые первые)
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(desc(ChatMessage.created_at))
            .limit(max_entries)
        )
        messages = list(session.scalars(stmt).all())
        messages.reverse()  # разворачиваем: старые → новые

        # Берём только последние window_size * 2 сообщений (пар user+assistant)
        if len(messages) > effective_window * 2:
            messages = messages[-(effective_window * 2):]

        entries = [
            ChatHistoryEntry(
                role=msg.role,
                content=msg.content,
                created_at=msg.created_at,
                generation_log_id=msg.generation_log_id,
            )
            for msg in messages
        ]

        # Общее количество сообщений в сессии
        total_stmt = select(func.count()).select_from(ChatMessage).where(
            ChatMessage.session_id == session_id
        )
        total = session.scalar(total_stmt) or 0

        return ChatWindow(
            session_id=session_id,
            entries=entries,
            total_messages=total,
        )

    def format_chat_history_for_prompt(
        self,
        session: Session,
        session_id: int,
        window_size: int | None = None,
    ) -> str:
        """Загрузить историю как текстовый блок для prompt.

        Форматирует сообщения в формат:
            Пользователь: вопрос
            Ассистент: ответ
        """
        window = self.load_chat_window(session, session_id, window_size)
        if not window.entries:
            return ""

        lines: list[str] = []
        for entry in window.entries:
            role_label = "Пользователь" if entry.role == "user" else "Ассистент"
            lines.append(f"{role_label}: {entry.content}")
        return "\n\n".join(lines)

    # ───────────────────────────────────────────────────────
    # Внутренние методы
    # ───────────────────────────────────────────────────────

    @staticmethod
    def _touch_session(session: Session, session_id: int) -> None:
        """Обновить last_message_at при новом сообщении."""
        chat_session = session.get(ChatSession, session_id)
        if chat_session is not None:
            chat_session.last_message_at = datetime.now(timezone.utc)
            session.flush()
