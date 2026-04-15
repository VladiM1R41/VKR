# Jarvis Layer 1

Layer 1 is the ingestion layer of the project. It discovers articles from researched RSS feeds, stores normalized records in PostgreSQL, enriches HTML-first articles asynchronously, tracks provenance and run metrics, and maintains source health signals.

The implementation in this repository follows:
- `docs/FINAL_LAYER_1_GUIDE.md`
- `docs/DATABASE_DESIGN_FINAL_v2.md`

## Implemented Scope

- PostgreSQL schema for `sources`, `news`, `news_raw`, `ingestion_runs`, `ingestion_errors`
- Alembic migrations and source bootstrap
- Universal RSS parsing through `BeautifulSoup(..., "xml")`
- Exact dedupe by `canonical_url`
- Conditional GET with `ETag` and `Last-Modified`
- HTML enrichment through `trafilatura` and source-specific extractors
- RSS-first extraction for `ТАСС`, `РБК`, `iXBT`, `АиФ`
- Deferred enrichment with Celery queues
- Scheduler with jitter, distributed lock, backpressure and graceful worker settings
- Health dashboard, date audit and daily health check
- Fixture-based regression tests for all researched RSS feeds

## Project Layout

```text
src/jarvis/
  core/        settings, logging, exceptions
  db/          SQLAlchemy models and sessions
  ingestion/   collectors, extraction, services, tasks, CLI
alembic/       migrations
tests/         unit tests and RSS fixtures
sources/       research notes and source profiles
docs/          architecture and implementation guide
```

## Prerequisites

- Python 3.12+
- Docker Desktop
- PostgreSQL and Redis through `docker compose`

## Environment

Copy `.env.example` to `.env` and adjust values if needed.

Key variables:

| Variable | Purpose |
|---|---|
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | PostgreSQL connection |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | Redis connection for Celery, locks and pending markers |
| `APP_ENV` | Environment name |
| `APP_DEBUG` | Debug mode flag |
| `APP_LOG_LEVEL` | Root log level |
| `APP_LOG_JSON` | `true` for JSON console logs, `false` for readable text |
| `APP_LOG_DIR` | Directory for rotating log files |
| `SOURCE_BUDGET_SECONDS` | Per-source discovery budget |
| `SOURCE_LOCK_TTL_SECONDS` | Redis lock TTL, must stay strictly above budget; recommended `600` for budget `300` |
| `SCHEDULER_TICK_SECONDS` | Celery Beat dispatch interval |
| `CRAWL_JITTER_RATIO` | Stable scheduler jitter ratio |

## Install

```powershell
cd C:\code\diplom
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-test.txt
```

## Start Infrastructure

```powershell
docker compose up -d
```

## Apply Migrations And Seed Sources

```powershell
$env:PYTHONPATH='src'
alembic upgrade head
python scripts\seed_sources.py
```

## Manual Commands

Discovery:

```powershell
$env:PYTHONPATH='src'
python -m jarvis.ingestion.cli.run_source --source "Lenta.ru"
```

HTML enrichment:

```powershell
$env:PYTHONPATH='src'
python -m jarvis.ingestion.cli.enrich_source --source "BFM.ru" --limit 10
```

Health and audits:

```powershell
$env:PYTHONPATH='src'
python -m jarvis.ingestion.cli.health_report
python -m jarvis.ingestion.cli.health_report --json
python -m jarvis.ingestion.cli.audit_dates
python -m jarvis.ingestion.cli.daily_health_check --dry-run
python -m jarvis.ingestion.cli.daily_health_check
```

## Celery Worker And Beat

Worker:

```powershell
cd C:\code\diplom
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH='src'
.\.venv\Scripts\celery -A jarvis.ingestion.tasks.celery_app worker -Q collector_queue,enrichment_queue -l info --pool=solo --without-mingle --without-gossip
```

Beat:

```powershell
cd C:\code\diplom
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH='src'
.\.venv\Scripts\celery -A jarvis.ingestion.tasks.celery_app beat -l info
```

## Tests

```powershell
$env:PYTHONPATH='src'
python -m pytest tests\unit -q
```

## Logs

- Main file: `logs/collector.log`
- Logs are structured and rotated automatically
- Successful HTTP requests are intentionally suppressed
- The important events are source-run completion, extraction failures, health transitions and scheduler summaries

## Scope Boundary

Layer 1 is responsible for collection, normalization, provenance and operational health. Semantic clustering and cross-source event reasoning belong to the next layers.
