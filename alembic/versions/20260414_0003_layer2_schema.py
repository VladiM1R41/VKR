"""create layer2 processing schema

Revision ID: 20260414_0003
Revises: 20260412_0002
Create Date: 2026-04-14 19:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260414_0003"
down_revision = "20260412_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("type IN ('person','organization','location')", name="ck_entities_type"),
        sa.UniqueConstraint("normalized_name", "type", name="uq_entities_normalized_name_type"),
    )
    op.create_index("idx_entities_type", "entities", ["type"], unique=False)
    op.create_index("idx_entities_mention_count", "entities", ["mention_count"], unique=False)

    op.create_table(
        "entity_profiles",
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mention_freq_baseline", sa.Float(), nullable=True),
        sa.Column("mention_freq_current", sa.Float(), nullable=True),
        sa.Column("sentiment_baseline", sa.Float(), nullable=True),
        sa.Column("sentiment_current", sa.Float(), nullable=True),
        sa.Column("source_diversity", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trend_direction", sa.String(length=20), nullable=False, server_default=sa.text("'stable'")),
        sa.Column("last_updated", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "trend_direction IN ('ascending','descending','stable','cyclic')",
            name="ck_entity_profiles_trend_direction",
        ),
    )

    op.create_table(
        "news_entities",
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("news_id", "entity_id", name="pk_news_entities"),
    )
    op.create_index("idx_news_entities_entity", "news_entities", ["entity_id"], unique=False)

    op.create_table(
        "entity_cooccurrences",
        sa.Column("entity_a_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_b_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("co_mention_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("entity_a_id", "entity_b_id", name="pk_entity_cooccurrences"),
        sa.CheckConstraint("entity_a_id < entity_b_id", name="ck_entity_cooccurrences_order"),
    )
    op.create_index("idx_entity_cooccurrences_b", "entity_cooccurrences", ["entity_b_id"], unique=False)

    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("name", name="uq_topics_name"),
    )

    op.create_table(
        "news_topics",
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.PrimaryKeyConstraint("news_id", "topic_id", name="pk_news_topics"),
        sa.CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_news_topics_confidence"),
    )
    op.create_index("idx_news_topics_topic", "news_topics", ["topic_id"], unique=False)

    op.create_table(
        "term_vocabulary",
        sa.Column("term", sa.String(length=100), primary_key=True),
        sa.Column("doc_frequency", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("collection_frequency", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.execute(
        """
        CREATE INDEX idx_term_trgm
        ON term_vocabulary
        USING gin (term gin_trgm_ops)
        """
    )

    op.create_table(
        "collocations",
        sa.Column("term_a", sa.String(length=100), nullable=False),
        sa.Column("term_b", sa.String(length=100), nullable=False),
        sa.Column("pmi_score", sa.Float(), nullable=True),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("term_a", "term_b", name="pk_collocations"),
    )
    op.create_index("idx_collocations_a_pmi", "collocations", ["term_a", "pmi_score"], unique=False)

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.SmallInteger(), nullable=False),
        sa.Column("zone", sa.String(length=10), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("zone IN ('title','body')", name="ck_chunks_zone"),
        sa.UniqueConstraint("qdrant_point_id", name="uq_chunks_qdrant_point_id"),
    )
    op.create_index("idx_chunks_news", "chunks", ["news_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_chunks_news", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("idx_collocations_a_pmi", table_name="collocations")
    op.drop_table("collocations")

    op.execute("DROP INDEX IF EXISTS idx_term_trgm")
    op.drop_table("term_vocabulary")

    op.drop_index("idx_news_topics_topic", table_name="news_topics")
    op.drop_table("news_topics")

    op.drop_table("topics")

    op.drop_index("idx_entity_cooccurrences_b", table_name="entity_cooccurrences")
    op.drop_table("entity_cooccurrences")

    op.drop_index("idx_news_entities_entity", table_name="news_entities")
    op.drop_table("news_entities")

    op.drop_table("entity_profiles")

    op.drop_index("idx_entities_mention_count", table_name="entities")
    op.drop_index("idx_entities_type", table_name="entities")
    op.drop_table("entities")
