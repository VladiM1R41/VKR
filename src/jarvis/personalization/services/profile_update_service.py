"""Profile update services for Layer 4."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.core.settings import get_settings
from jarvis.db.models import (
    News,
    NewsEntity,
    NewsTopic,
    User,
    UserEntityWeight,
    UserInteraction,
    UserSourcePreference,
    UserTopicWeight,
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class ProfileUpdateResult:
    """Summary of one profile update run."""

    interaction_id: int
    user_id: int
    news_id: int
    signal: float
    updated_topics: int
    updated_entities: int
    updated_source_id: int


class SessionProfileStore:
    """Redis-backed short-term profile state."""

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

    @staticmethod
    def _key(user_id: int) -> str:
        return f"user:session:{user_id}"

    def load(self, user_id: int) -> dict:
        """Load current short-term profile."""
        raw = self._get_redis().get(self._key(user_id))
        if not raw:
            return {
                "recent_news_ids": [],
                "recent_topic_ids": [],
                "recent_entity_ids": [],
                "last_updated_at": None,
            }
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "recent_news_ids": [],
                "recent_topic_ids": [],
                "recent_entity_ids": [],
                "last_updated_at": None,
            }
        return {
            "recent_news_ids": list(payload.get("recent_news_ids", [])),
            "recent_topic_ids": list(payload.get("recent_topic_ids", [])),
            "recent_entity_ids": list(payload.get("recent_entity_ids", [])),
            "last_updated_at": payload.get("last_updated_at"),
        }

    def update(self, user_id: int, *, news_id: int, topic_ids: list[int], entity_ids: list[int]) -> dict:
        """Update session profile with newest interaction context."""
        current = self.load(user_id)
        current["recent_news_ids"] = self._prepend_unique(current["recent_news_ids"], news_id, limit=20)
        for topic_id in topic_ids:
            current["recent_topic_ids"] = self._prepend_unique(current["recent_topic_ids"], topic_id, limit=20)
        for entity_id in entity_ids:
            current["recent_entity_ids"] = self._prepend_unique(current["recent_entity_ids"], entity_id, limit=20)
        current["last_updated_at"] = datetime.now(UTC).isoformat()
        self._get_redis().setex(self._key(user_id), self._ttl_seconds, json.dumps(current))
        return current

    @staticmethod
    def _prepend_unique(values: list[int], new_value: int, *, limit: int) -> list[int]:
        items = [int(new_value), *[int(item) for item in values if int(item) != int(new_value)]]
        return items[:limit]


class ProfileUpdateService:
    """Update long-term and short-term profile from interaction events."""

    def __init__(self, session_store: SessionProfileStore | None = None, alpha: float = 0.25) -> None:
        self._session_store = session_store or SessionProfileStore()
        self._alpha = alpha

    def update_from_interaction(self, session: Session, interaction_id: int) -> ProfileUpdateResult:
        """Apply one persisted interaction to user profile state."""
        interaction = session.get(UserInteraction, interaction_id)
        if interaction is None:
            raise ValueError(f"Interaction {interaction_id} not found")

        user = session.get(User, interaction.user_id)
        news = session.get(News, interaction.news_id)
        if user is None:
            raise ValueError(f"User {interaction.user_id} not found")
        if news is None:
            raise ValueError(f"News {interaction.news_id} not found")

        signal = self._resolve_signal(interaction.action, interaction.dwell_time_sec)
        topic_ids = list(
            session.scalars(
                select(NewsTopic.topic_id).where(NewsTopic.news_id == interaction.news_id)
            ).all()
        )
        entity_ids = list(
            session.scalars(
                select(NewsEntity.entity_id).where(NewsEntity.news_id == interaction.news_id)
            ).all()
        )

        updated_topics = self._update_topic_weights(session, interaction.user_id, topic_ids, signal)
        updated_entities = self._update_entity_weights(session, interaction.user_id, entity_ids, signal)
        self._update_source_preference(session, user, news.source_id, signal)
        self._session_store.update(
            interaction.user_id,
            news_id=interaction.news_id,
            topic_ids=topic_ids,
            entity_ids=entity_ids,
        )
        session.commit()

        return ProfileUpdateResult(
            interaction_id=interaction.id,
            user_id=interaction.user_id,
            news_id=interaction.news_id,
            signal=signal,
            updated_topics=updated_topics,
            updated_entities=updated_entities,
            updated_source_id=news.source_id,
        )

    def get_session_profile(self, user_id: int) -> dict:
        """Return current short-term session profile."""
        return self._session_store.load(user_id)

    def _update_topic_weights(self, session: Session, user_id: int, topic_ids: list[int], signal: float) -> int:
        updated = 0
        for topic_id in topic_ids:
            row = session.get(UserTopicWeight, {"user_id": user_id, "topic_id": topic_id})
            if row is None:
                row = UserTopicWeight(user_id=user_id, topic_id=topic_id, weight=0.5)
                session.add(row)
            row.weight = self._apply_signal(row.weight, signal)
            updated += 1
        return updated

    def _update_entity_weights(self, session: Session, user_id: int, entity_ids: list[int], signal: float) -> int:
        updated = 0
        for entity_id in entity_ids:
            row = session.get(UserEntityWeight, {"user_id": user_id, "entity_id": entity_id})
            if row is None:
                row = UserEntityWeight(user_id=user_id, entity_id=entity_id, weight=0.5)
                session.add(row)
            row.weight = self._apply_signal(row.weight, signal)
            updated += 1
        return updated

    def _update_source_preference(self, session: Session, user: User, source_id: int, signal: float) -> None:
        settings = dict(user.settings or {})
        source_scores = dict(settings.get("source_affinity_scores", {}))
        current_score = float(source_scores.get(str(source_id), 0.5))
        next_score = self._apply_signal(current_score, signal)
        source_scores[str(source_id)] = round(next_score, 4)
        settings["source_affinity_scores"] = source_scores
        user.settings = settings

        preference = "neutral"
        if next_score >= 0.65:
            preference = "preferred"
        elif next_score <= 0.35:
            preference = "blocked"

        row = session.get(UserSourcePreference, {"user_id": user.id, "source_id": source_id})
        if row is None:
            row = UserSourcePreference(user_id=user.id, source_id=source_id, preference=preference)
            session.add(row)
        else:
            row.preference = preference

    def _apply_signal(self, current_weight: float, signal: float) -> float:
        normalized_target = _clamp01((signal + 1.0) / 2.0)
        next_weight = (1.0 - self._alpha) * float(current_weight) + self._alpha * normalized_target
        return round(_clamp01(next_weight), 4)

    @staticmethod
    def _resolve_signal(action: str, dwell_time_sec: float | None) -> float:
        if action == "like":
            return 1.0
        if action == "share":
            return 1.0
        if action == "save":
            return 0.8
        if action == "dislike":
            return -1.0
        if action == "hide":
            return -0.8
        if action == "click":
            if dwell_time_sec is not None and dwell_time_sec >= 45:
                return 0.7
            if dwell_time_sec is not None and dwell_time_sec < 10:
                return 0.3
            return 0.3
        if action == "read":
            if dwell_time_sec is not None and dwell_time_sec >= 45:
                return 0.7
            return 0.5
        return 0.0
