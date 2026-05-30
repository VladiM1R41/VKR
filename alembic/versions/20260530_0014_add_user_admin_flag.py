"""add user admin flag

Revision ID: 20260530_0014
Revises: 20260501_0013
Create Date: 2026-05-30 17:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0014"
down_revision = "20260501_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("UPDATE users SET is_admin = true WHERE id = 1")
    op.execute(
        """
        UPDATE users
        SET is_admin = true
        WHERE id = (
            SELECT id
            FROM users
            WHERE password_hash IS NOT NULL
            ORDER BY created_at ASC NULLS LAST, id ASC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
