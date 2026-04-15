"""Add run_kind to ingestion_runs and backfill existing rows.

Revision ID: 20260412_0002
Revises: 20260411_0001
Create Date: 2026-04-12 03:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_0002"
down_revision = "20260411_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "run_kind",
            sa.String(length=20),
            nullable=True,
            server_default=sa.text("'discovery'"),
        ),
    )

    op.execute("UPDATE ingestion_runs SET run_kind = 'discovery'")
    op.execute(
        """
        UPDATE ingestion_runs
        SET run_kind = 'enrichment'
        WHERE http_status IS NULL
          AND response_bytes IS NULL
          AND sent_etag IS NULL
          AND sent_if_modified_since IS NULL
          AND received_etag IS NULL
          AND received_last_modified IS NULL
        """
    )
    op.execute(
        """
        UPDATE sources AS s
        SET last_crawled = latest.last_finished_at
        FROM (
            SELECT
                source_id,
                MAX(COALESCE(finished_at, started_at)) AS last_finished_at
            FROM ingestion_runs
            WHERE run_kind = 'discovery'
            GROUP BY source_id
        ) AS latest
        WHERE latest.source_id = s.id
        """
    )

    op.alter_column("ingestion_runs", "run_kind", nullable=False)
    op.create_check_constraint(
        "ck_ingestion_runs_run_kind",
        "ingestion_runs",
        "run_kind IN ('discovery','enrichment')",
    )
    op.create_index(
        "ix_ingestion_runs_source_kind_started",
        "ingestion_runs",
        ["source_id", "run_kind", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_source_kind_started", table_name="ingestion_runs")
    op.drop_constraint("ck_ingestion_runs_run_kind", "ingestion_runs", type_="check")
    op.drop_column("ingestion_runs", "run_kind")
