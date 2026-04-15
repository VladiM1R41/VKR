"""create layer5 generation schema

Revision ID: 20260414_0006
Revises: 20260414_0005
Create Date: 2026-04-14 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision = "20260414_0006"
down_revision = "20260414_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    digest_columns = {column["name"] for column in inspector.get_columns("digests")}

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_message_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.execute("CREATE INDEX idx_chat_sessions_user ON chat_sessions (user_id, last_message_at DESC)")

    op.create_table(
        "generation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("rag_mode", sa.String(20), nullable=False),
        sa.Column("model_name", sa.String(50), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.String(10), nullable=True),
        sa.Column("documents_used", JSONB(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "rag_mode IN ('standard','crag','self_rag','graph_rag','agentic')",
            name="ck_generation_logs_rag_mode",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('LOW','MEDIUM','HIGH','TOP')",
            name="ck_generation_logs_confidence",
        ),
    )
    op.execute("CREATE INDEX idx_gen_logs_mode ON generation_logs (rag_mode, created_at DESC)")
    op.execute("CREATE INDEX idx_gen_logs_user ON generation_logs (user_id, created_at DESC)")

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "generation_log_id",
            sa.Integer(),
            sa.ForeignKey("generation_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_chat_messages_role"),
    )
    op.execute("CREATE INDEX idx_chat_messages_session ON chat_messages (session_id, created_at)")

    if "generation_log_id" not in digest_columns:
        op.add_column("digests", sa.Column("generation_log_id", sa.Integer(), nullable=True))

    digest_fks = {fk["name"] for fk in inspector.get_foreign_keys("digests") if fk.get("name")}
    if "fk_digests_generation_log" not in digest_fks:
        op.create_foreign_key(
            "fk_digests_generation_log",
            "digests",
            "generation_logs",
            ["generation_log_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_digests_generation_log", "digests", type_="foreignkey")

    op.execute("DROP INDEX IF EXISTS idx_chat_messages_session")
    op.drop_table("chat_messages")

    op.execute("DROP INDEX IF EXISTS idx_gen_logs_user")
    op.execute("DROP INDEX IF EXISTS idx_gen_logs_mode")
    op.drop_table("generation_logs")

    op.execute("DROP INDEX IF EXISTS idx_chat_sessions_user")
    op.drop_table("chat_sessions")
