from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from jarvis.db.models.user import User
from jarvis.personalization.models.preferences_models import (
    ExplicitPreferencesUpdateRequest,
    SourcePreferenceInput,
    TopicPreferenceInput,
    TrackedKeywordInput,
    UserProfilePatch,
)
from jarvis.personalization.services.preferences_service import ExplicitPreferencesService


def test_preferences_request_requires_identity() -> None:
    with pytest.raises(ValueError, match="Either user_id or username"):
        ExplicitPreferencesUpdateRequest(profile=UserProfilePatch())


def test_tracked_keyword_is_normalized() -> None:
    payload = TrackedKeywordInput(keyword="  санкции   ес  ")
    assert payload.keyword == "санкции ес"


def test_apply_profile_patch_merges_settings() -> None:
    user = User(
        id=1,
        username="alice",
        email="old@example.com",
        telegram_id=100,
        settings={"timezone": "Europe/Moscow", "digest_style": "brief"},
        created_at=datetime.utcnow(),
    )
    payload = ExplicitPreferencesUpdateRequest(
        profile=UserProfilePatch(
            user_id=1,
            username="alice",
            email="new@example.com",
            settings={"digest_style": "detailed"},
        )
    )

    ExplicitPreferencesService()._apply_profile_patch(user, payload)

    assert user.email == "new@example.com"
    assert user.settings == {
        "timezone": "Europe/Moscow",
        "digest_style": "detailed",
    }


def test_update_preferences_validates_fk_ids() -> None:
    session = Mock()
    service = ExplicitPreferencesService()

    user = User(
        id=7,
        username="alice",
        settings={},
        created_at=datetime.utcnow(),
    )

    service._resolve_user = Mock(return_value=user)
    service._replace_topic_weights = Mock()
    service._replace_entity_weights = Mock()
    service._replace_entity_subscriptions = Mock()
    service._replace_tracked_keywords = Mock()
    service._replace_source_preferences = Mock()
    service.get_preferences = Mock()

    def fake_assert_existing_ids(_session, _model, ids, label):
        if label == "topic" and ids == [99]:
            raise ValueError("Unknown topic ids: [99]")

    service._assert_existing_ids = fake_assert_existing_ids  # type: ignore[method-assign]

    payload = ExplicitPreferencesUpdateRequest(
        profile=UserProfilePatch(user_id=7, username="alice"),
        topic_weights=[TopicPreferenceInput(topic_id=99, weight=0.8)],
    )

    with pytest.raises(ValueError, match=r"Unknown topic ids: \[99\]"):
        service.update_preferences(session, payload)


def test_update_preferences_replaces_all_collections() -> None:
    session = Mock()
    service = ExplicitPreferencesService()

    user = User(
        id=9,
        username="bob",
        settings={"timezone": "Europe/Moscow"},
        created_at=datetime.utcnow(),
    )

    service._resolve_user = Mock(return_value=user)
    service._assert_existing_ids = Mock()
    service.get_preferences = Mock(return_value="response")
    service._replace_topic_weights = Mock()
    service._replace_entity_weights = Mock()
    service._replace_entity_subscriptions = Mock()
    service._replace_tracked_keywords = Mock()
    service._replace_source_preferences = Mock()

    payload = ExplicitPreferencesUpdateRequest(
        profile=UserProfilePatch(user_id=9, username="bob", settings={"digest_style": "brief"}),
        topic_weights=[TopicPreferenceInput(topic_id=1, weight=0.7)],
        tracked_keywords=[TrackedKeywordInput(keyword="ipo")],
        source_preferences=[SourcePreferenceInput(source_id=5, preference="preferred")],
    )

    result = service.update_preferences(session, payload)

    assert result == "response"
    service._replace_topic_weights.assert_called_once()
    service._replace_entity_weights.assert_called_once()
    service._replace_entity_subscriptions.assert_called_once()
    service._replace_tracked_keywords.assert_called_once()
    service._replace_source_preferences.assert_called_once()
    session.commit.assert_called_once()
    assert user.settings == {
        "timezone": "Europe/Moscow",
        "digest_style": "brief",
    }
