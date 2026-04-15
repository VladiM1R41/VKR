"""Alert candidate generation for Layer 4."""

from __future__ import annotations

from collections import defaultdict
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.generation.services.answer_generation_service import AnswerGenerationService
    from jarvis.generation.services.context_assembler import NewsWithContext

from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.core.logging import log_event
from jarvis.db.models import (
    Entity,
    EntityProfile,
    News,
    NewsEntity,
    NewsTopic,
    Source,
    Topic,
    User,
    UserEntitySubscription,
)
from jarvis.personalization.models.alert_models import AlertBatch, AlertCandidate
from jarvis.personalization.services.profile_update_service import SessionProfileStore
from jarvis.personalization.services.runtime_state import AlertRateLimiter


logger = logging.getLogger(__name__)


class AlertService:
    """Generate alert candidates for subscriptions, spikes and breaking news."""

    def __init__(
        self,
        *,
        session_profile_store: SessionProfileStore | None = None,
        rate_limiter: AlertRateLimiter | None = None,
    ) -> None:
        self._session_profile_store = session_profile_store or SessionProfileStore()
        self._rate_limiter = rate_limiter or AlertRateLimiter()

    def build_alert_batch(
        self,
        session: Session,
        *,
        user_id: int,
        news_ids: list[int],
    ) -> AlertBatch:
        """Build alert candidates for one user over a set of fresh articles."""
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        session_profile = self._session_profile_store.load(user_id)
        tracked_topic_ids = set(int(item) for item in session_profile.get("recent_topic_ids", []))

        subscription_rows = session.execute(
            select(
                Entity.id,
                Entity.name,
                UserEntitySubscription.alert_on_news,
                UserEntitySubscription.alert_on_spike,
            )
            .select_from(UserEntitySubscription)
            .join(Entity, Entity.id == UserEntitySubscription.entity_id)
            .where(UserEntitySubscription.user_id == user_id)
        ).all()
        subscribed_entities = {int(row[0]): str(row[1]) for row in subscription_rows}
        # Флаги для каждой подписки: entity_id → {alert_on_news, alert_on_spike}
        subscription_flags: dict[int, dict[str, bool]] = {
            int(row[0]): {"alert_on_news": bool(row[2]), "alert_on_spike": bool(row[3])}
            for row in subscription_rows
        }

        spike_entities = self._load_spike_entities(session)
        topic_names = self._load_topic_names(session)
        source_names = self._load_source_names(session)

        alerts: list[AlertCandidate] = []

        for news in self._load_news(session, news_ids):
            entity_ids = self._load_news_entity_ids(session, news.id)
            topic_ids = self._load_news_topic_ids(session, news.id)

            for entity_id in entity_ids:
                if entity_id in subscribed_entities:
                    flags = subscription_flags.get(entity_id, {})
                    if flags.get("alert_on_news", True):
                        alerts.append(
                            AlertCandidate(
                                user_id=user_id,
                                news_id=news.id,
                                alert_type="alert_news",
                                title=news.title,
                                body=f"Новая статья по подписке на сущность: {subscribed_entities[entity_id]}",
                                entity_id=entity_id,
                                source_name=source_names.get(news.source_id),
                                urgency=news.urgency,
                                score=0.9,
                                reasons=[f"entity_subscription: {subscribed_entities[entity_id]}"],
                                published_at=news.published_at,
                            )
                        )
                if entity_id in spike_entities:
                    flags = subscription_flags.get(entity_id, {})
                    if entity_id not in subscribed_entities or flags.get("alert_on_spike", True):
                        alerts.append(
                            AlertCandidate(
                                user_id=user_id,
                                news_id=news.id,
                                alert_type="alert_spike",
                                title=news.title,
                                body=f"Зафиксирован spike по сущности: {spike_entities[entity_id]}",
                                entity_id=entity_id,
                                source_name=source_names.get(news.source_id),
                                urgency=news.urgency,
                                score=0.85,
                                reasons=[f"entity_spike: {spike_entities[entity_id]}"],
                                published_at=news.published_at,
                            )
                        )

            if news.information_type == "breaking" and self._has_high_match(topic_ids, tracked_topic_ids):
                matched_topic = next((topic_names[topic_id] for topic_id in topic_ids if topic_id in tracked_topic_ids and topic_id in topic_names), None)
                alerts.append(
                    AlertCandidate(
                        user_id=user_id,
                        news_id=news.id,
                        alert_type="breaking_match",
                        title=news.title,
                        body="Breaking-news с высоким совпадением с текущим краткосрочным интересом пользователя",
                        topic=matched_topic,
                        source_name=source_names.get(news.source_id),
                        urgency=news.urgency,
                        score=0.95,
                        reasons=["breaking_news", f"session_topic_match: {matched_topic}" if matched_topic else "session_topic_match"],
                        published_at=news.published_at,
                    )
                )

            for topic_id in topic_ids:
                if topic_id in tracked_topic_ids and news.urgency in {"critical", "high"}:
                    alerts.append(
                        AlertCandidate(
                            user_id=user_id,
                            news_id=news.id,
                            alert_type="tracked_topic_update",
                            title=news.title,
                            body=f"Важное обновление по теме: {topic_names.get(topic_id, str(topic_id))}",
                            topic=topic_names.get(topic_id),
                            source_name=source_names.get(news.source_id),
                            urgency=news.urgency,
                            score=0.8,
                            reasons=[f"tracked_topic: {topic_names.get(topic_id, str(topic_id))}"],
                            published_at=news.published_at,
                        )
                    )

        deduped = self._deduplicate(alerts)
        eligible = [
            alert
            for alert in deduped
            if self._rate_limiter.is_allowed(
                user_id=alert.user_id,
                alert_type=alert.alert_type,
                news_id=alert.news_id,
            )
        ]
        eligible.sort(key=lambda item: item.score, reverse=True)
        return AlertBatch(user_id=user_id, alerts=eligible)

    def mark_alerts_sent(self, batch: AlertBatch) -> int:
        """Mark emitted alerts in cooldown state."""
        for alert in batch.alerts:
            self._rate_limiter.mark_sent(
                user_id=alert.user_id,
                alert_type=alert.alert_type,
                news_id=alert.news_id,
            )
        return len(batch.alerts)

    @staticmethod
    def _load_spike_entities(session: Session) -> dict[int, str]:
        stmt = (
            select(EntityProfile.entity_id, Entity.name)
            .select_from(EntityProfile)
            .join(Entity, Entity.id == EntityProfile.entity_id)
            .where(
                EntityProfile.mention_freq_current.is_not(None),
                EntityProfile.mention_freq_baseline.is_not(None),
                EntityProfile.mention_freq_current > EntityProfile.mention_freq_baseline * 2.0,
            )
        )
        return {int(row[0]): str(row[1]) for row in session.execute(stmt).all()}

    @staticmethod
    def _load_topic_names(session: Session) -> dict[int, str]:
        return {int(row.id): str(row.name) for row in session.scalars(select(Topic)).all()}

    @staticmethod
    def _load_source_names(session: Session) -> dict[int, str]:
        return {int(row.id): str(row.name) for row in session.scalars(select(Source)).all()}

    @staticmethod
    def _load_news(session: Session, news_ids: list[int]) -> list[News]:
        return list(session.scalars(select(News).where(News.id.in_(news_ids))).all())

    @staticmethod
    def _load_news_entity_ids(session: Session, news_id: int) -> list[int]:
        return list(session.scalars(select(NewsEntity.entity_id).where(NewsEntity.news_id == news_id)).all())

    @staticmethod
    def _load_news_topic_ids(session: Session, news_id: int) -> list[int]:
        return list(session.scalars(select(NewsTopic.topic_id).where(NewsTopic.news_id == news_id)).all())

    @staticmethod
    def _has_high_match(topic_ids: list[int], tracked_topic_ids: set[int]) -> bool:
        return any(topic_id in tracked_topic_ids for topic_id in topic_ids)

    @staticmethod
    def _deduplicate(alerts: list[AlertCandidate]) -> list[AlertCandidate]:
        best: dict[tuple[int, int, str, int | None, str | None], AlertCandidate] = {}
        for alert in alerts:
            key = (alert.user_id, alert.news_id, alert.alert_type, alert.entity_id, alert.topic)
            existing = best.get(key)
            if existing is None or alert.score > existing.score:
                best[key] = alert
        return list(best.values())

    # ───────────────────────────────────────────────────────
    # Связь со Слоем 5: генерация текста alert
    # ───────────────────────────────────────────────────────

    @staticmethod
    def generate_alert_text(
        alert: AlertCandidate,
        news: News,
        source_name: str,
        generation_service: AnswerGenerationService,
    ) -> tuple[str, int | None]:
        """Сгенерировать текст alert через L5.

        Args:
            alert: AlertCandidate из build_alert_batch.
            news: объект новости.
            source_name: название источника.
            generation_service: AnswerGenerationService из Слоя 5.

        Returns:
            (alert_text, generation_log_id)
        """
        news_item = NewsWithContext(
            news_id=news.id,
            source_name=source_name,
            title=news.title,
            content=news.content or "",
            snippet=news.snippet_lead or "",
            trust_score=float((news.extra or {}).get("trust_score", 0.5)),
            content_grade=int(news.content_grade or 6),
            published_at=news.published_at,
        )

        result = generation_service.generate_alert(
            news_item=news_item,
            alert_reason=alert.body,
            user_id=alert.user_id,
        )

        log_event(
            logger,
            logging.INFO,
            "alert_text_generated",
            user_id=alert.user_id,
            news_id=news.id,
            alert_type=alert.alert_type,
            generation_log_id=result.generation_log_id,
        )

        return result.answer_text, result.generation_log_id
