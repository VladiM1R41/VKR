"""Implicit interaction logging and session seen-history for Layer 4."""

from __future__ import annotations

from datetime import UTC, datetime
import json

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.core.settings import get_settings
from jarvis.db.models import News, SearchLog, User, UserInteraction
from jarvis.personalization.models.interaction_models import (
    InteractionEventRequest,
    InteractionEventResponse,
    SeenHistoryResponse,
)

_SIGNAL_BY_ACTION: dict[str, tuple[str, float]] = {
    "like": ("like", 1.0),
    "share": ("share", 1.0),
    "save": ("save", 0.8),
    "read_long": ("read", 0.7),
    "click_short": ("click", 0.3),
    "click": ("click", 0.3),
    "skip": ("hide", -0.1),
    "hide": ("hide", -0.8),
    "dislike": ("dislike", -1.0),
    "read": ("read", 0.5),
}


class SessionSeenHistory:
    """Redis-backed short-term seen state."""

    def __init__(self, ttl_seconds: int = 60 * 60 * 24) -> None:
        self._settings = get_settings()
        self._ttl_seconds = ttl_seconds
        self._redis: Redis | None = None

    def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(
                self._settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    def _key(self, *, user_id: int | None = None, session_id: str | None = None) -> str:
        if session_id:
            return f"user:seen:session:{session_id}"
        if user_id is None:
            raise ValueError("Either user_id or session_id must be provided")
        return f"user:seen:{user_id}"

    def mark_seen(self, news_id: int, *, user_id: int | None = None, session_id: str | None = None) -> None:
        """Append one article to short-term seen state."""
        redis = self._get_redis()
        key = self._key(user_id=user_id, session_id=session_id)
        payload = json.dumps({"news_id": news_id, "seen_at": datetime.now(UTC).isoformat()})
        redis.lpush(key, payload)
        redis.ltrim(key, 0, 199)
        redis.expire(key, self._ttl_seconds)

    def get_seen_news_ids(
        self,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[int]:
        """Return unique seen article ids, newest first."""
        redis = self._get_redis()
        key = self._key(user_id=user_id, session_id=session_id)
        rows = redis.lrange(key, 0, max(limit - 1, 0))
        result: list[int] = []
        seen: set[int] = set()
        for row in rows:
            try:
                news_id = int(json.loads(row)["news_id"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if news_id in seen:
                continue
            seen.add(news_id)
            result.append(news_id)
        return result

    def get_state(
        self,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> SeenHistoryResponse:
        """Return normalized seen state."""
        return SeenHistoryResponse(
            user_id=user_id,
            session_id=session_id,
            news_ids=self.get_seen_news_ids(user_id=user_id, session_id=session_id, limit=limit),
        )

    def clear(self, *, user_id: int | None = None, session_id: str | None = None) -> bool:
        """Drop short-term seen state."""
        redis = self._get_redis()
        return bool(redis.delete(self._key(user_id=user_id, session_id=session_id)))


class InteractionLoggingService:
    """Service for persisting implicit feedback and updating short-term session state."""

    def __init__(self, seen_history: SessionSeenHistory | None = None) -> None:
        self._seen_history = seen_history or SessionSeenHistory()

    def log_interaction(
        self,
        session: Session,
        event: InteractionEventRequest,
        *,
        commit: bool = True,
    ) -> InteractionEventResponse:
        """Persist one interaction event and update short-term seen history."""
        self._ensure_user_and_news(session, user_id=event.user_id, news_id=event.news_id)
        if event.search_log_id is not None:
            self._ensure_search_log(session, search_log_id=event.search_log_id, user_id=event.user_id)

        stored_action, signal = _SIGNAL_BY_ACTION[event.action]
        interaction = UserInteraction(
            user_id=event.user_id,
            news_id=event.news_id,
            action=stored_action,
            dwell_time_sec=event.dwell_time_sec,
            search_log_id=event.search_log_id,
        )
        session.add(interaction)
        session.flush()
        if commit:
            session.commit()
        session.refresh(interaction)

        self._seen_history.mark_seen(event.news_id, user_id=event.user_id)
        if event.session_id:
            self._seen_history.mark_seen(event.news_id, session_id=event.session_id)

        return InteractionEventResponse(
            interaction_id=interaction.id,
            user_id=interaction.user_id,
            news_id=interaction.news_id,
            stored_action=interaction.action,
            derived_signal=signal,
            dwell_time_sec=interaction.dwell_time_sec,
            search_log_id=interaction.search_log_id,
            created_at=interaction.created_at,
        )

    def get_seen_history(
        self,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> SeenHistoryResponse:
        """Read current short-term seen state."""
        return self._seen_history.get_state(user_id=user_id, session_id=session_id, limit=limit)

    def clear_seen_history(self, *, user_id: int | None = None, session_id: str | None = None) -> bool:
        """Clear current short-term seen state."""
        return self._seen_history.clear(user_id=user_id, session_id=session_id)

    @staticmethod
    def _ensure_user_and_news(session: Session, *, user_id: int, news_id: int) -> None:
        if session.get(User, user_id) is None:
            raise ValueError(f"User {user_id} not found")
        if session.get(News, news_id) is None:
            raise ValueError(f"News {news_id} not found")

    @staticmethod
    def _ensure_search_log(session: Session, *, search_log_id: int, user_id: int) -> None:
        found = session.scalar(
            select(SearchLog.id).where(
                SearchLog.id == search_log_id,
                SearchLog.user_id == user_id,
            )
        )
        if found is None:
            raise ValueError(f"Search log {search_log_id} not found for user {user_id}")
