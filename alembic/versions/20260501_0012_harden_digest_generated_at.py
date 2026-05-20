"""harden digest generated_at defaults

Revision ID: 20260501_0012
Revises: 20260428_0011
Create Date: 2026-05-01 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260501_0012"
down_revision = "20260428_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE digests SET generated_at = NOW() WHERE generated_at IS NULL")
    op.alter_column(
        "digests",
        "generated_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )


def downgrade() -> None:
    op.alter_column(
        "digests",
        "generated_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        nullable=True,
        server_default=None,
    )
