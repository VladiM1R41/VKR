"""add backpressure skip ingestion run status

Revision ID: 20260423_0010
Revises: 20260423_0009
Create Date: 2026-04-23 22:15:00
"""

from __future__ import annotations

from alembic import op


revision = "20260423_0010"
down_revision = "20260423_0009"
branch_labels = None
depends_on = None


RUN_STATUSES_WITH_BACKPRESSURE = (
    "'running','success','partial','failed','timeout','skipped_304','skipped_backpressure'"
)
RUN_STATUSES_WITHOUT_BACKPRESSURE = "'running','success','partial','failed','timeout','skipped_304'"


def upgrade() -> None:
    op.execute("ALTER TABLE ingestion_runs DROP CONSTRAINT IF EXISTS ck_ingestion_runs_status")
    op.execute(
        f"""
        ALTER TABLE ingestion_runs
        ADD CONSTRAINT ck_ingestion_runs_status
        CHECK (status IN ({RUN_STATUSES_WITH_BACKPRESSURE}))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ingestion_runs DROP CONSTRAINT IF EXISTS ck_ingestion_runs_status")
    op.execute(
        f"""
        ALTER TABLE ingestion_runs
        ADD CONSTRAINT ck_ingestion_runs_status
        CHECK (status IN ({RUN_STATUSES_WITHOUT_BACKPRESSURE}))
        """
    )
