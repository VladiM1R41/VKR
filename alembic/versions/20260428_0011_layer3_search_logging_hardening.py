"""harden layer3 search logging schema

Revision ID: 20260428_0011
Revises: 20260423_0010
Create Date: 2026-04-28 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260428_0011"
down_revision = "20260423_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_logs",
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "search_logs",
        sa.Column("retrieval_mode", sa.String(length=40), nullable=False, server_default=sa.text("'qdrant_hybrid'")),
    )
    op.add_column("search_logs", sa.Column("search_type", sa.String(length=40), nullable=True))
    op.add_column("search_logs", sa.Column("rag_mode", sa.String(length=40), nullable=True))
    op.add_column(
        "search_logs",
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "search_results",
        sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0.0")),
    )
    op.create_index("idx_search_logs_retrieval_mode", "search_logs", ["retrieval_mode"], unique=False)
    op.create_index("idx_search_logs_cache_hit", "search_logs", ["cache_hit"], unique=False)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_layer3_fts_ru
        ON news
        USING GIN (
            to_tsvector(
                'russian',
                coalesce(title, '') || ' ' || coalesce(content, '') || ' ' || coalesce(snippet_lead, '')
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_news_layer3_fts_ru")
    op.drop_index("idx_search_logs_cache_hit", table_name="search_logs")
    op.drop_index("idx_search_logs_retrieval_mode", table_name="search_logs")
    op.drop_column("search_results", "score")
    op.drop_column("search_logs", "extra")
    op.drop_column("search_logs", "rag_mode")
    op.drop_column("search_logs", "search_type")
    op.drop_column("search_logs", "retrieval_mode")
    op.drop_column("search_logs", "cache_hit")
