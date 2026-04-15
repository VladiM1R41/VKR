from pathlib import Path

from jarvis.db.models.digest import Digest
from jarvis.db.models.digest_item import DigestItem
from jarvis.db.models.user import User
from jarvis.db.models.user_embedding import UserEmbedding
from jarvis.db.models.user_entity_subscription import UserEntitySubscription
from jarvis.db.models.user_entity_weight import UserEntityWeight
from jarvis.db.models.user_interaction import UserInteraction
from jarvis.db.models.user_source_preference import UserSourcePreference
from jarvis.db.models.user_topic_weight import UserTopicWeight
from jarvis.db.models.user_tracked_keyword import UserTrackedKeyword


def test_layer4_model_primary_keys_match_contract() -> None:
    assert list(UserTopicWeight.__table__.primary_key.columns.keys()) == ["user_id", "topic_id"]
    assert list(UserEntityWeight.__table__.primary_key.columns.keys()) == ["user_id", "entity_id"]
    assert list(UserEntitySubscription.__table__.primary_key.columns.keys()) == ["user_id", "entity_id"]
    assert list(UserTrackedKeyword.__table__.primary_key.columns.keys()) == ["user_id", "keyword"]
    assert list(UserSourcePreference.__table__.primary_key.columns.keys()) == ["user_id", "source_id"]
    assert list(UserEmbedding.__table__.primary_key.columns.keys()) == ["user_id"]
    assert list(DigestItem.__table__.primary_key.columns.keys()) == ["digest_id", "news_id"]


def test_layer4_model_columns_match_contract() -> None:
    assert "password_hash" in User.__table__.columns
    assert "last_active_at" in User.__table__.columns
    assert "signal_weight" not in UserInteraction.__table__.columns
    assert "content_text" in Digest.__table__.columns
    assert "summary_text" not in Digest.__table__.columns
    assert "snippet" in DigestItem.__table__.columns
    assert "reason" not in DigestItem.__table__.columns


def test_layer4_migration_contains_expected_tables() -> None:
    migration = Path("alembic/versions/20260414_0005_layer4_personalization_schema.py").read_text(encoding="utf-8")
    for table_name in [
        "users",
        "user_topic_weights",
        "user_entity_weights",
        "user_entity_subscriptions",
        "user_tracked_keywords",
        "user_source_preferences",
        "user_interactions",
        "user_embeddings",
        "digests",
        "digest_items",
    ]:
        assert f'"{table_name}"' in migration
