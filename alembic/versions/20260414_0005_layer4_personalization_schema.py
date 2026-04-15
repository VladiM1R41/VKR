"""create layer4 personalization schema

Revision ID: 20260414_0005
Revises: 20260414_0004
Create Date: 2026-04-14 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


revision = "20260414_0005"
down_revision = "20260414_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("settings", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_active_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("idx_users_telegram_id", "users", ["telegram_id"], unique=False)

    op.create_table(
        "user_topic_weights",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("weight BETWEEN 0.0 AND 1.0", name="ck_user_topic_weights_weight"),
        sa.PrimaryKeyConstraint("user_id", "topic_id"),
    )
    op.create_index("idx_user_topic_weights_user", "user_topic_weights", ["user_id"])

    op.create_table(
        "user_entity_weights",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("weight BETWEEN 0.0 AND 1.0", name="ck_user_entity_weights_weight"),
        sa.PrimaryKeyConstraint("user_id", "entity_id"),
    )
    op.create_index("idx_user_entity_weights_user", "user_entity_weights", ["user_id"])

    op.create_table(
        "user_entity_subscriptions",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_on_spike", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("alert_on_news", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("user_id", "entity_id"),
    )
    op.create_index("idx_user_entity_subscriptions_user", "user_entity_subscriptions", ["user_id"])

    op.create_table(
        "user_tracked_keywords",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("user_id", "keyword"),
    )
    op.create_index("idx_user_tracked_keywords_user", "user_tracked_keywords", ["user_id"])

    op.create_table(
        "user_source_preferences",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preference", sa.String(20), nullable=False, server_default=sa.text("'neutral'")),
        sa.CheckConstraint(
            "preference IN ('preferred','neutral','blocked')",
            name="ck_user_source_preferences_preference",
        ),
        sa.PrimaryKeyConstraint("user_id", "source_id"),
    )
    op.create_index("idx_user_source_preferences_user", "user_source_preferences", ["user_id"])

    op.create_table(
        "user_interactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("dwell_time_sec", sa.Float(), nullable=True),
        sa.Column("search_log_id", sa.Integer(), sa.ForeignKey("search_logs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "action IN ('click','read','like','dislike','save','hide','share')",
            name="ck_user_interactions_action",
        ),
    )
    op.execute("CREATE INDEX idx_interactions_user ON user_interactions (user_id, created_at DESC)")
    op.create_index("idx_interactions_news", "user_interactions", ["news_id"])
    op.create_index("idx_interactions_action", "user_interactions", ["user_id", "action"])

    op.create_table(
        "user_embeddings",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "digests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("digest_type", sa.String(20), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("audio_path", sa.String(500), nullable=True),
        sa.Column("generation_log_id", sa.Integer(), nullable=True),
        sa.Column("news_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("topics_covered", ARRAY(sa.Text()), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "digest_type IN ('morning','evening','weekly','on_demand')",
            name="ck_digests_digest_type",
        ),
    )
    op.execute("CREATE INDEX idx_digests_user_type ON digests (user_id, digest_type, generated_at DESC)")

    op.create_table(
        "digest_items",
        sa.Column("digest_id", sa.Integer(), sa.ForeignKey("digests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("digest_id", "news_id"),
    )


def downgrade() -> None:
    op.drop_table("digest_items")

    op.execute("DROP INDEX IF EXISTS idx_digests_user_type")
    op.drop_table("digests")

    op.drop_table("user_embeddings")

    op.drop_index("idx_interactions_action", table_name="user_interactions")
    op.drop_index("idx_interactions_news", table_name="user_interactions")
    op.execute("DROP INDEX IF EXISTS idx_interactions_user")
    op.drop_table("user_interactions")

    op.drop_index("idx_user_source_preferences_user", table_name="user_source_preferences")
    op.drop_table("user_source_preferences")

    op.drop_index("idx_user_tracked_keywords_user", table_name="user_tracked_keywords")
    op.drop_table("user_tracked_keywords")

    op.drop_index("idx_user_entity_subscriptions_user", table_name="user_entity_subscriptions")
    op.drop_table("user_entity_subscriptions")

    op.drop_index("idx_user_entity_weights_user", table_name="user_entity_weights")
    op.drop_table("user_entity_weights")

    op.drop_index("idx_user_topic_weights_user", table_name="user_topic_weights")
    op.drop_table("user_topic_weights")

    op.drop_index("idx_users_telegram_id", table_name="users")
    op.drop_table("users")
