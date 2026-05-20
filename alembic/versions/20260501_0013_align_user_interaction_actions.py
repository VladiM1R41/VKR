"""align user interaction action constraint

Revision ID: 20260501_0013
Revises: 20260501_0012
Create Date: 2026-05-01 12:20:00
"""

from __future__ import annotations

from alembic import op


revision = "20260501_0013"
down_revision = "20260501_0012"
branch_labels = None
depends_on = None


CANONICAL_AND_LEGACY_ACTIONS = (
    "'click','read','like','dislike','save','hide','share','read_long','click_short','skip'"
)
PREVIOUS_ACTIONS = "'click','read','like','dislike','save','hide','share'"


def upgrade() -> None:
    op.execute("ALTER TABLE user_interactions DROP CONSTRAINT IF EXISTS ck_user_interactions_action")
    op.execute(
        f"""
        ALTER TABLE user_interactions
        ADD CONSTRAINT ck_user_interactions_action
        CHECK (action IN ({CANONICAL_AND_LEGACY_ACTIONS}))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_interactions DROP CONSTRAINT IF EXISTS ck_user_interactions_action")
    op.execute(
        f"""
        ALTER TABLE user_interactions
        ADD CONSTRAINT ck_user_interactions_action
        CHECK (action IN ({PREVIOUS_ACTIONS}))
        """
    )
