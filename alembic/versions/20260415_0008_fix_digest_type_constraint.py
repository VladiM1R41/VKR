"""fix digest type constraint for current layer4 contract

Revision ID: 20260415_0008
Revises: 20260415_0007
Create Date: 2026-04-15 00:10:00
"""

from __future__ import annotations

from alembic import op


revision = "20260415_0008"
down_revision = "20260415_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE digests DROP CONSTRAINT IF EXISTS ck_digests_digest_type")
    op.execute(
        """
        ALTER TABLE digests
        ADD CONSTRAINT ck_digests_digest_type
        CHECK (digest_type IN ('morning','evening','weekly','on_demand'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE digests DROP CONSTRAINT IF EXISTS ck_digests_digest_type")
