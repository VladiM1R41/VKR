"""Read/update service for explicit personalization preferences."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from jarvis.db.models import (
    Entity,
    Source,
    Topic,
    User,
    UserEntitySubscription,
    UserEntityWeight,
    UserSourcePreference,
    UserTopicWeight,
    UserTrackedKeyword,
)
from jarvis.personalization.models.preferences_models import (
    EntityPreferenceInput,
    EntityPreferenceView,
    EntitySubscriptionInput,
    EntitySubscriptionView,
    ExplicitPreferencesResponse,
    ExplicitPreferencesUpdateRequest,
    SourcePreferenceInput,
    SourcePreferenceView,
    TopicPreferenceInput,
    TopicPreferenceView,
    TrackedKeywordInput,
    TrackedKeywordView,
    UserProfileView,
)


class ExplicitPreferencesService:
    """Service for reading and updating explicit Layer 4 preferences."""

    def get_preferences(self, session: Session, user_id: int) -> ExplicitPreferencesResponse:
        """Load one user's explicit preferences snapshot."""
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        topics = self._load_name_map(session, Topic, self._ids_from_rows(
            session.scalars(
                select(UserTopicWeight).where(UserTopicWeight.user_id == user_id)
            ).all(),
            attr_name="topic_id",
        ))
        entities = self._load_name_map(session, Entity, self._ids_from_rows(
            [
                *session.scalars(
                    select(UserEntityWeight).where(UserEntityWeight.user_id == user_id)
                ).all(),
                *session.scalars(
                    select(UserEntitySubscription).where(UserEntitySubscription.user_id == user_id)
                ).all(),
            ],
            attr_name="entity_id",
        ))
        sources = self._load_name_map(session, Source, self._ids_from_rows(
            session.scalars(
                select(UserSourcePreference).where(UserSourcePreference.user_id == user_id)
            ).all(),
            attr_name="source_id",
        ))

        topic_weights = session.scalars(
            select(UserTopicWeight).where(UserTopicWeight.user_id == user_id)
        ).all()
        entity_weights = session.scalars(
            select(UserEntityWeight).where(UserEntityWeight.user_id == user_id)
        ).all()
        entity_subscriptions = session.scalars(
            select(UserEntitySubscription).where(UserEntitySubscription.user_id == user_id)
        ).all()
        tracked_keywords = session.scalars(
            select(UserTrackedKeyword).where(UserTrackedKeyword.user_id == user_id)
        ).all()
        source_preferences = session.scalars(
            select(UserSourcePreference).where(UserSourcePreference.user_id == user_id)
        ).all()

        return ExplicitPreferencesResponse(
            profile=UserProfileView(
                user_id=user.id,
                username=user.username,
                email=user.email,
                telegram_id=user.telegram_id,
                settings=dict(user.settings or {}),
                created_at=user.created_at,
                last_active_at=user.last_active_at,
            ),
            topic_weights=[
                TopicPreferenceView(
                    topic_id=item.topic_id,
                    name=topics.get(item.topic_id),
                    weight=item.weight,
                )
                for item in topic_weights
            ],
            entity_weights=[
                EntityPreferenceView(
                    entity_id=item.entity_id,
                    name=entities.get(item.entity_id),
                    weight=item.weight,
                )
                for item in entity_weights
            ],
            entity_subscriptions=[
                EntitySubscriptionView(
                    entity_id=item.entity_id,
                    name=entities.get(item.entity_id),
                    alert_on_spike=item.alert_on_spike,
                    alert_on_news=item.alert_on_news,
                )
                for item in entity_subscriptions
            ],
            tracked_keywords=[
                TrackedKeywordView(keyword=item.keyword)
                for item in tracked_keywords
            ],
            source_preferences=[
                SourcePreferenceView(
                    source_id=item.source_id,
                    name=sources.get(item.source_id),
                    preference=item.preference,
                )
                for item in source_preferences
            ],
        )

    def update_preferences(
        self,
        session: Session,
        payload: ExplicitPreferencesUpdateRequest,
    ) -> ExplicitPreferencesResponse:
        """Replace explicit-preference collections and patch profile fields."""
        user = self._resolve_user(session, payload)
        self._apply_profile_patch(user, payload)

        self._assert_existing_ids(session, Topic, [item.topic_id for item in payload.topic_weights], "topic")
        self._assert_existing_ids(session, Entity, [item.entity_id for item in payload.entity_weights], "entity")
        self._assert_existing_ids(
            session,
            Entity,
            [item.entity_id for item in payload.entity_subscriptions],
            "entity",
        )
        self._assert_existing_ids(
            session,
            Source,
            [item.source_id for item in payload.source_preferences],
            "source",
        )

        self._replace_topic_weights(session, user.id, payload.topic_weights)
        self._replace_entity_weights(session, user.id, payload.entity_weights)
        self._replace_entity_subscriptions(session, user.id, payload.entity_subscriptions)
        self._replace_tracked_keywords(session, user.id, payload.tracked_keywords)
        self._replace_source_preferences(session, user.id, payload.source_preferences)

        session.add(user)
        session.commit()
        return self.get_preferences(session, user.id)

    def _resolve_user(self, session: Session, payload: ExplicitPreferencesUpdateRequest) -> User:
        profile = payload.profile
        user = session.get(User, profile.user_id) if profile.user_id else None

        if user is None and profile.username:
            user = session.scalar(select(User).where(User.username == profile.username))

        if user is None:
            if not profile.username:
                raise ValueError("username is required when creating a new user")
            user = User(
                username=profile.username,
                email=profile.email,
                telegram_id=profile.telegram_id,
                settings=dict(profile.settings or {}),
            )
            session.add(user)
            session.flush()

        return user

    def _apply_profile_patch(self, user: User, payload: ExplicitPreferencesUpdateRequest) -> None:
        profile = payload.profile
        if profile.username:
            user.username = profile.username
        if profile.email is not None:
            user.email = profile.email
        if profile.telegram_id is not None:
            user.telegram_id = profile.telegram_id
        if profile.settings is not None:
            merged = dict(user.settings or {})
            merged.update(profile.settings)
            user.settings = merged

    def _replace_topic_weights(
        self,
        session: Session,
        user_id: int,
        items: list[TopicPreferenceInput],
    ) -> None:
        session.execute(delete(UserTopicWeight).where(UserTopicWeight.user_id == user_id))
        for item in items:
            session.add(UserTopicWeight(user_id=user_id, topic_id=item.topic_id, weight=item.weight))

    def _replace_entity_weights(
        self,
        session: Session,
        user_id: int,
        items: list[EntityPreferenceInput],
    ) -> None:
        session.execute(delete(UserEntityWeight).where(UserEntityWeight.user_id == user_id))
        for item in items:
            session.add(UserEntityWeight(user_id=user_id, entity_id=item.entity_id, weight=item.weight))

    def _replace_entity_subscriptions(
        self,
        session: Session,
        user_id: int,
        items: list[EntitySubscriptionInput],
    ) -> None:
        session.execute(delete(UserEntitySubscription).where(UserEntitySubscription.user_id == user_id))
        for item in items:
            session.add(
                UserEntitySubscription(
                    user_id=user_id,
                    entity_id=item.entity_id,
                    alert_on_spike=item.alert_on_spike,
                    alert_on_news=item.alert_on_news,
                )
            )

    def _replace_tracked_keywords(
        self,
        session: Session,
        user_id: int,
        items: list[TrackedKeywordInput],
    ) -> None:
        session.execute(delete(UserTrackedKeyword).where(UserTrackedKeyword.user_id == user_id))
        for item in items:
            session.add(UserTrackedKeyword(user_id=user_id, keyword=item.keyword))

    def _replace_source_preferences(
        self,
        session: Session,
        user_id: int,
        items: list[SourcePreferenceInput],
    ) -> None:
        session.execute(delete(UserSourcePreference).where(UserSourcePreference.user_id == user_id))
        for item in items:
            session.add(
                UserSourcePreference(
                    user_id=user_id,
                    source_id=item.source_id,
                    preference=item.preference,
                )
            )

    @staticmethod
    def _ids_from_rows(rows: Iterable[object], attr_name: str) -> list[int]:
        ids = {int(getattr(row, attr_name)) for row in rows}
        return sorted(ids)

    @staticmethod
    def _load_name_map(session: Session, model, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        records = session.scalars(select(model).where(model.id.in_(ids))).all()
        return {int(record.id): str(record.name) for record in records}

    @staticmethod
    def _assert_existing_ids(session: Session, model, ids: list[int], label: str) -> None:
        if not ids:
            return
        unique_ids = sorted(set(ids))
        existing = session.scalars(select(model.id).where(model.id.in_(unique_ids))).all()
        missing = sorted(set(unique_ids) - {int(item) for item in existing})
        if missing:
            raise ValueError(f"Unknown {label} ids: {missing}")
