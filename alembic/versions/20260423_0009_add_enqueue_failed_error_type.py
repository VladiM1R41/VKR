"""add enqueue_failed ingestion error type

Revision ID: 20260423_0009
Revises: 20260415_0008
Create Date: 2026-04-23 18:05:00
"""

from __future__ import annotations

from alembic import op


revision = "20260423_0009"
down_revision = "20260415_0008"
branch_labels = None
depends_on = None


ERROR_TYPES_WITH_ENQUEUE_FAILED = (
    "'network','http_4xx','http_5xx','http_429','rss_parse','data_missing',"
    "'date_parse','extraction','db_constraint','enqueue_failed','unknown'"
)
ERROR_TYPES_WITHOUT_ENQUEUE_FAILED = (
    "'network','http_4xx','http_5xx','http_429','rss_parse','data_missing',"
    "'date_parse','extraction','db_constraint','unknown'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE ingestion_errors DROP CONSTRAINT IF EXISTS ck_ingestion_errors_error_type")
    op.execute(
        f"""
        ALTER TABLE ingestion_errors
        ADD CONSTRAINT ck_ingestion_errors_error_type
        CHECK (error_type IN ({ERROR_TYPES_WITH_ENQUEUE_FAILED}))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ingestion_errors DROP CONSTRAINT IF EXISTS ck_ingestion_errors_error_type")
    op.execute(
        f"""
        ALTER TABLE ingestion_errors
        ADD CONSTRAINT ck_ingestion_errors_error_type
        CHECK (error_type IN ({ERROR_TYPES_WITHOUT_ENQUEUE_FAILED}))
        """
    )
