"""create layer3 search logging schema

Revision ID: 20260414_0004
Revises: 20260414_0003
Create Date: 2026-04-14 23:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260414_0004"
down_revision = "20260414_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("resolved_query", sa.Text(), nullable=True),
        sa.Column("intent", sa.String(length=20), nullable=True),
        sa.Column("num_results", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("retrieval_time_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("top_result_ids", sa.ARRAY(sa.Integer()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_search_logs_created_at", "search_logs", ["created_at"], unique=False)

    op.create_table(
        "search_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_id", sa.Integer(), sa.ForeignKey("search_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column("was_clicked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dwell_time_sec", sa.Float(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "rank_position IS NULL OR rank_position > 0",
            name="ck_search_results_rank_position",
        ),
        sa.UniqueConstraint("search_id", "news_id", name="uq_search_results_search_news"),
    )
    op.create_index("idx_search_results_search", "search_results", ["search_id"], unique=False)
    op.create_index("idx_search_results_news", "search_results", ["news_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_search_results_news", table_name="search_results")
    op.drop_index("idx_search_results_search", table_name="search_results")
    op.drop_table("search_results")

    op.drop_index("idx_search_logs_created_at", table_name="search_logs")
    op.drop_table("search_logs")
