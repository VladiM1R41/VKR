"""align legacy layer4 schema with current layer4/5 contracts

Revision ID: 20260415_0007
Revises: 20260414_0006
Create Date: 2026-04-15 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


revision = "20260415_0007"
down_revision = "20260414_0006"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    users_columns = _column_names(inspector, "users")
    if "password_hash" not in users_columns:
        op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    if "last_active_at" not in users_columns:
        op.add_column("users", sa.Column("last_active_at", sa.TIMESTAMP(timezone=True), nullable=True))

    user_topic_columns = _column_names(inspector, "user_topic_weights")
    if "updated_at" not in user_topic_columns:
        op.add_column(
            "user_topic_weights",
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_topic_weights_user_topic "
        "ON user_topic_weights (user_id, topic_id)"
    )

    user_entity_columns = _column_names(inspector, "user_entity_weights")
    if "updated_at" not in user_entity_columns:
        op.add_column(
            "user_entity_weights",
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_entity_weights_user_entity "
        "ON user_entity_weights (user_id, entity_id)"
    )

    source_pref_columns = _column_names(inspector, "user_source_preferences")
    if "preference" not in source_pref_columns:
        op.add_column(
            "user_source_preferences",
            sa.Column("preference", sa.String(20), nullable=True),
        )
        if "level" in source_pref_columns:
            op.execute(
                """
                UPDATE user_source_preferences
                SET preference = CASE level
                    WHEN 'high' THEN 'preferred'
                    WHEN 'low' THEN 'blocked'
                    ELSE 'neutral'
                END
                WHERE preference IS NULL
                """
            )
        op.execute(
            "UPDATE user_source_preferences SET preference = 'neutral' WHERE preference IS NULL"
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_source_preferences_user_source "
        "ON user_source_preferences (user_id, source_id)"
    )

    subscription_columns = _column_names(inspector, "user_entity_subscriptions")
    if "alert_on_spike" not in subscription_columns:
        op.add_column(
            "user_entity_subscriptions",
            sa.Column("alert_on_spike", sa.Boolean(), nullable=True),
        )
    if "alert_on_news" not in subscription_columns:
        op.add_column(
            "user_entity_subscriptions",
            sa.Column("alert_on_news", sa.Boolean(), nullable=True),
        )
    if "is_active" in subscription_columns:
        op.execute(
            """
            UPDATE user_entity_subscriptions
            SET alert_on_spike = COALESCE(alert_on_spike, is_active),
                alert_on_news = COALESCE(alert_on_news, is_active)
            """
        )
    op.execute(
        """
        UPDATE user_entity_subscriptions
        SET alert_on_spike = COALESCE(alert_on_spike, true),
            alert_on_news = COALESCE(alert_on_news, true)
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_entity_subscriptions_user_entity "
        "ON user_entity_subscriptions (user_id, entity_id)"
    )

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_tracked_keywords_user_keyword "
        "ON user_tracked_keywords (user_id, keyword)"
    )

    interaction_columns = _column_names(inspector, "user_interactions")
    if "signal_weight" not in interaction_columns:
        op.add_column(
            "user_interactions",
            sa.Column("signal_weight", sa.Float(), nullable=True),
        )

    digest_columns = _column_names(inspector, "digests")
    if "content_text" not in digest_columns:
        op.add_column("digests", sa.Column("content_text", sa.Text(), nullable=True))
    if "news_count" not in digest_columns:
        op.add_column("digests", sa.Column("news_count", sa.Integer(), nullable=True))
    if "topics_covered" not in digest_columns:
        op.add_column("digests", sa.Column("topics_covered", ARRAY(sa.Text()), nullable=True))
    if "generated_at" not in digest_columns:
        op.add_column("digests", sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=True))

    if "summary_text" in digest_columns:
        op.execute(
            """
            UPDATE digests
            SET content_text = COALESCE(content_text, summary_text),
                generated_at = COALESCE(generated_at, delivered_at, created_at)
            """
        )
    else:
        op.execute(
            "UPDATE digests SET generated_at = COALESCE(generated_at, created_at)"
        )
    op.execute("UPDATE digests SET content_text = COALESCE(content_text, '')")
    op.execute(
        """
        UPDATE digests d
        SET news_count = COALESCE(
            d.news_count,
            (SELECT COUNT(*) FROM digest_items di WHERE di.digest_id = d.id),
            0
        )
        """
    )

    digest_item_columns = _column_names(inspector, "digest_items")
    if "snippet" not in digest_item_columns:
        op.add_column("digest_items", sa.Column("snippet", sa.Text(), nullable=True))
        if "reason" in digest_item_columns:
            op.execute("UPDATE digest_items SET snippet = reason WHERE snippet IS NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_digest_items_digest_news "
        "ON digest_items (digest_id, news_id)"
    )

    user_embedding_columns = _column_names(inspector, "user_embeddings")
    if "embedding_model" not in user_embedding_columns:
        op.add_column("user_embeddings", sa.Column("embedding_model", sa.String(100), nullable=True))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_digest_items_digest_news")
    op.execute("DROP INDEX IF EXISTS uq_user_tracked_keywords_user_keyword")
    op.execute("DROP INDEX IF EXISTS uq_user_entity_subscriptions_user_entity")
    op.execute("DROP INDEX IF EXISTS uq_user_source_preferences_user_source")
    op.execute("DROP INDEX IF EXISTS uq_user_entity_weights_user_entity")
    op.execute("DROP INDEX IF EXISTS uq_user_topic_weights_user_topic")
