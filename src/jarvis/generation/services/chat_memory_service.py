"""Chat memory helpers for Layer 5 sliding window and summary buffer."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from jarvis.core.settings import get_settings
from jarvis.generation.services.chat_service import ChatService


logger = logging.getLogger(__name__)


class ChatMemoryService:
    """Build prompt-ready chat memory with Redis-backed summary buffer."""

    def __init__(self, chat_service: ChatService | None = None) -> None:
        self._chat_service = chat_service or ChatService()
        self._settings = get_settings()
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            from redis import Redis

            self._redis = Redis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
        return self._redis

    @staticmethod
    def _summary_key(session_id: int) -> str:
        return f"chat:summary:{session_id}"

    def get_summary(self, session_id: int) -> str:
        try:
            data = self._get_redis().get(self._summary_key(session_id))
            return data or ""
        except Exception as exc:
            logger.warning("chat_summary_get_failed: %s", exc)
            return ""

    def set_summary(self, session_id: int, summary: str, ttl_seconds: int = 86400) -> None:
        try:
            self._get_redis().setex(self._summary_key(session_id), ttl_seconds, summary)
        except Exception as exc:
            logger.warning("chat_summary_set_failed: %s", exc)

    def build_memory_block(
        self,
        session: Session,
        session_id: int,
        *,
        window_size: int | None = None,
    ) -> str:
        summary = self.get_summary(session_id)
        history = self._chat_service.format_chat_history_for_prompt(
            session,
            session_id,
            window_size=window_size,
        )
        parts = []
        if summary:
            parts.append(f"Краткая сводка прошлого диалога:\n{summary}")
        if history:
            parts.append(f"Последние сообщения:\n{history}")
        return "\n\n".join(parts)

    def refresh_summary_if_needed(
        self,
        session: Session,
        session_id: int,
        *,
        max_messages_before_summary: int = 12,
    ) -> str:
        window = self._chat_service.load_chat_window(session, session_id, window_size=max_messages_before_summary)
        if window.total_messages < max_messages_before_summary:
            return self.get_summary(session_id)

        tail_entries = window.entries[-6:]
        summary_payload = [
            {
                "role": entry.role,
                "content": entry.content[:200],
            }
            for entry in tail_entries
        ]
        summary = json.dumps(summary_payload, ensure_ascii=False)
        self.set_summary(session_id, summary)
        return summary

