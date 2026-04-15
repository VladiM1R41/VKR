"""create layer1 schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260411_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("engine", sa.String(length=20), nullable=False, server_default=sa.text("'auto'")),
        sa.Column("delivery_mode", sa.String(length=10), nullable=False, server_default=sa.text("'pull'")),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("crawl_interval", sa.Integer(), nullable=False, server_default=sa.text("15")),
        sa.Column("crawl_delay", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default=sa.text("'periodic'")),
        sa.Column("trust_score", sa.Float(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("reliability", sa.String(length=1), nullable=False, server_default=sa.text("'C'")),
        sa.Column("default_info_type", sa.String(length=20), nullable=False, server_default=sa.text("'daily'")),
        sa.Column("default_content_type", sa.String(length=20), nullable=False, server_default=sa.text("'news'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_user_added", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_crawled", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("health_status", sa.String(length=10), nullable=False, server_default=sa.text("'green'")),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_run_id", sa.Integer(), nullable=True),
        sa.Column("parse_success_rate", sa.Float(), nullable=True),
        sa.Column("extraction_success_rate", sa.Float(), nullable=True),
        sa.Column("latest_published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source_utility", sa.Float(), nullable=True),
        sa.Column("avg_latency_minutes", sa.Float(), nullable=True),
        sa.Column("legal_status", sa.String(length=20), nullable=False, server_default=sa.text("'public_rss'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("type IN ('rss','telegram','website','api')", name="ck_sources_type"),
        sa.CheckConstraint("engine IN ('auto','httpx','playwright')", name="ck_sources_engine"),
        sa.CheckConstraint("delivery_mode IN ('push','pull')", name="ck_sources_delivery_mode"),
        sa.CheckConstraint("priority IN ('continuous','periodic','control')", name="ck_sources_priority"),
        sa.CheckConstraint("trust_score BETWEEN 0.0 AND 1.0", name="ck_sources_trust_score"),
        sa.CheckConstraint("reliability IN ('A','B','C','D','E')", name="ck_sources_reliability"),
        sa.CheckConstraint(
            "default_info_type IN ('breaking','daily','analytics','reference')",
            name="ck_sources_default_info_type",
        ),
        sa.CheckConstraint(
            "default_content_type IN ('news','analysis','press_release','opinion')",
            name="ck_sources_default_content_type",
        ),
        sa.CheckConstraint("health_status IN ('green','yellow','red')", name="ck_sources_health_status"),
        sa.CheckConstraint("consecutive_failures >= 0", name="ck_sources_consecutive_failures"),
        sa.CheckConstraint(
            "parse_success_rate IS NULL OR (parse_success_rate BETWEEN 0.0 AND 1.0)",
            name="ck_sources_parse_success_rate",
        ),
        sa.CheckConstraint(
            "extraction_success_rate IS NULL OR (extraction_success_rate BETWEEN 0.0 AND 1.0)",
            name="ck_sources_extraction_success_rate",
        ),
        sa.CheckConstraint(
            "source_utility IS NULL OR (source_utility BETWEEN 0.0 AND 1.0)",
            name="ck_sources_source_utility",
        ),
        sa.CheckConstraint(
            "legal_status IN ('public_rss','public_telegram','public_web','restricted')",
            name="ck_sources_legal_status",
        ),
    )
    op.create_index(
        "idx_sources_active",
        "sources",
        ["is_active"],
        unique=False,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index("idx_sources_type", "sources", ["type"], unique=False)
    op.create_index(
        "idx_sources_health",
        "sources",
        ["health_status"],
        unique=False,
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'running'")),
        sa.Column("items_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_duplicate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("http_errors_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("parse_errors_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("extraction_errors_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column("sent_etag", sa.Text(), nullable=True),
        sa.Column("sent_if_modified_since", sa.Text(), nullable=True),
        sa.Column("received_etag", sa.Text(), nullable=True),
        sa.Column("received_last_modified", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','success','partial','failed','timeout','skipped_304')",
            name="ck_ingestion_runs_status",
        ),
        sa.CheckConstraint("items_total >= 0", name="ck_ingestion_runs_items_total"),
        sa.CheckConstraint("items_new >= 0", name="ck_ingestion_runs_items_new"),
        sa.CheckConstraint("items_duplicate >= 0", name="ck_ingestion_runs_items_duplicate"),
        sa.CheckConstraint("items_failed >= 0", name="ck_ingestion_runs_items_failed"),
        sa.CheckConstraint("http_errors_count >= 0", name="ck_ingestion_runs_http_errors_count"),
        sa.CheckConstraint("parse_errors_count >= 0", name="ck_ingestion_runs_parse_errors_count"),
        sa.CheckConstraint(
            "extraction_errors_count >= 0",
            name="ck_ingestion_runs_extraction_errors_count",
        ),
        sa.CheckConstraint(
            "response_bytes IS NULL OR response_bytes >= 0",
            name="ck_ingestion_runs_response_bytes",
        ),
    )
    op.create_index("idx_ingestion_runs_source_started", "ingestion_runs", ["source_id", "started_at"], unique=False)
    op.create_index(
        "idx_ingestion_runs_status",
        "ingestion_runs",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status != 'success'"),
    )
    op.create_index("idx_ingestion_runs_started", "ingestion_runs", ["started_at"], unique=False)

    op.create_table(
        "news",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("snippet_lead", sa.Text(), nullable=True),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=True),
        sa.Column("channel_type", sa.String(length=20), nullable=False),
        sa.Column("information_type", sa.String(length=20), nullable=False, server_default=sa.text("'daily'")),
        sa.Column("content_type", sa.String(length=20), nullable=True, server_default=sa.text("'news'")),
        sa.Column("language", sa.String(length=5), nullable=False, server_default=sa.text("'ru'")),
        sa.Column("title_hash", sa.String(length=32), nullable=True),
        sa.Column("duplicate_of", sa.Integer(), sa.ForeignKey("news.id"), nullable=True),
        sa.Column("event_cluster_id", sa.Integer(), nullable=True),
        sa.Column("content_grade", sa.SmallInteger(), nullable=False, server_default=sa.text("6")),
        sa.Column("urgency", sa.String(length=20), nullable=False, server_default=sa.text("'normal'")),
        sa.Column("is_uncertain", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("content_status", sa.String(length=20), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("extraction_method", sa.String(length=40), nullable=True),
        sa.Column("raw_pub_date", sa.Text(), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("parser_version", sa.String(length=30), nullable=True),
        sa.Column("date_inferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "channel_type IN ('RSS','TELEGRAM','SCRAPE','API','ARCHIVE')",
            name="ck_news_channel_type",
        ),
        sa.CheckConstraint(
            "information_type IN ('breaking','daily','analytics','reference')",
            name="ck_news_information_type",
        ),
        sa.CheckConstraint(
            "content_type IN ('news','analysis','press_release','opinion')",
            name="ck_news_content_type",
        ),
        sa.CheckConstraint("content_grade BETWEEN 1 AND 6", name="ck_news_content_grade"),
        sa.CheckConstraint("urgency IN ('critical','high','normal')", name="ck_news_urgency"),
        sa.CheckConstraint(
            "content_status IN ('ok','partial','paywall','extraction_failed','low')",
            name="ck_news_content_status",
        ),
        sa.UniqueConstraint("canonical_url", name="uq_news_canonical_url"),
    )
    op.create_index("idx_news_canonical_url", "news", ["canonical_url"], unique=True)
    op.create_index("idx_news_source_published", "news", ["source_id", "published_at"], unique=False)
    op.create_index(
        "idx_news_ingestion_run",
        "news",
        ["ingestion_run_id"],
        unique=False,
        postgresql_where=sa.text("ingestion_run_id IS NOT NULL"),
    )
    op.create_index("idx_news_published", "news", ["published_at"], unique=False)
    op.create_index(
        "idx_news_title_hash",
        "news",
        ["title_hash"],
        unique=False,
        postgresql_where=sa.text("title_hash IS NOT NULL"),
    )
    op.create_index(
        "idx_news_event_cluster",
        "news",
        ["event_cluster_id"],
        unique=False,
        postgresql_where=sa.text("event_cluster_id IS NOT NULL"),
    )
    op.create_index(
        "idx_news_unprocessed",
        "news",
        ["id"],
        unique=False,
        postgresql_where=sa.text("processed = false"),
    )
    op.create_index("idx_news_ingested", "news", ["ingested_at"], unique=False)
    op.create_index("idx_news_language", "news", ["language"], unique=False)
    op.create_index(
        "idx_news_content_status",
        "news",
        ["content_status"],
        unique=False,
        postgresql_where=sa.text("content_status != 'ok'"),
    )

    op.create_table(
        "news_raw",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("raw_format", sa.String(length=10), nullable=True),
        sa.Column("parser_version", sa.String(length=30), nullable=True),
        sa.Column("collected_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("raw_format IN ('html','json','xml','text')", name="ck_news_raw_format"),
    )
    op.create_index("idx_news_raw_news", "news_raw", ["news_id"], unique=True)

    op.create_table(
        "ingestion_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("error_type", sa.String(length=30), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("error_traceback", sa.Text(), nullable=True),
        sa.Column("item_url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "error_type IN ('network','http_4xx','http_5xx','http_429','rss_parse','data_missing','date_parse','extraction','db_constraint','unknown')",
            name="ck_ingestion_errors_error_type",
        ),
    )
    op.create_index("idx_ingestion_errors_source_time", "ingestion_errors", ["source_id", "occurred_at"], unique=False)
    op.create_index("idx_ingestion_errors_run", "ingestion_errors", ["run_id"], unique=False)
    op.create_index("idx_ingestion_errors_type", "ingestion_errors", ["error_type"], unique=False)

    op.create_foreign_key(
        "fk_sources_last_run",
        "sources",
        "ingestion_runs",
        ["last_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_news_ingestion_run",
        "news",
        "ingestion_runs",
        ["ingestion_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_news_event_cluster",
        "news",
        "news",
        ["event_cluster_id"],
        ["id"],
        ondelete="SET NULL",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_news_event_cluster", "news", type_="foreignkey")
    op.drop_constraint("fk_news_ingestion_run", "news", type_="foreignkey")
    op.drop_constraint("fk_sources_last_run", "sources", type_="foreignkey")

    op.drop_index("idx_ingestion_errors_type", table_name="ingestion_errors")
    op.drop_index("idx_ingestion_errors_run", table_name="ingestion_errors")
    op.drop_index("idx_ingestion_errors_source_time", table_name="ingestion_errors")
    op.drop_table("ingestion_errors")

    op.drop_index("idx_news_raw_news", table_name="news_raw")
    op.drop_table("news_raw")

    op.drop_index("idx_news_content_status", table_name="news")
    op.drop_index("idx_news_language", table_name="news")
    op.drop_index("idx_news_ingested", table_name="news")
    op.drop_index("idx_news_unprocessed", table_name="news")
    op.drop_index("idx_news_event_cluster", table_name="news")
    op.drop_index("idx_news_title_hash", table_name="news")
    op.drop_index("idx_news_published", table_name="news")
    op.drop_index("idx_news_ingestion_run", table_name="news")
    op.drop_index("idx_news_source_published", table_name="news")
    op.drop_index("idx_news_canonical_url", table_name="news")
    op.drop_table("news")

    op.drop_index("idx_ingestion_runs_started", table_name="ingestion_runs")
    op.drop_index("idx_ingestion_runs_status", table_name="ingestion_runs")
    op.drop_index("idx_ingestion_runs_source_started", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")

    op.drop_index("idx_sources_health", table_name="sources")
    op.drop_index("idx_sources_type", table_name="sources")
    op.drop_index("idx_sources_active", table_name="sources")
    op.drop_table("sources")
