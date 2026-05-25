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
| `PROCESSING_BATCH_SIZE`, `PROCESSING_TICK_SECONDS`, `PROCESSING_LOCK_TTL_SECONDS` | Layer 2 processing worker cadence and lock settings |
| `PROCESSING_EMBEDDING_BACKEND` | Embedding backend for Layer 2 processing |
| `CELERY_ENABLE_LAYER4_SCHEDULE` | Enables optional Layer 4 personalization Beat jobs when `true` |

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

### Local Venv Runtime (Recommended For This MVP)

Use this mode on Windows/local development. Docker runs only PostgreSQL, Redis and Qdrant;
Celery Beat and workers run from the existing `.venv`, so the runtime does not rebuild
Python/ML dependencies and does not download Docker worker images.

```powershell
cd C:\code\diplom

docker compose up -d
powershell -ExecutionPolicy Bypass -File .\scripts\start_celery_runtime.ps1
```

The script sets the local runtime environment before starting Celery:

```powershell
$env:PYTHONPATH="src"
$env:PROCESSING_EMBEDDING_BACKEND="flagembedding"
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"
# HTTP_PROXY / HTTPS_PROXY / ALL_PROXY and lowercase variants are removed.
```

This local runtime starts:

- `collector@%h` for `collector_queue`
- `enrichment@%h` for `enrichment_queue`
- `processing@%h` for `processing_queue`
- Celery Beat for scheduled Layer 1-2 tasks

Useful safe variants:

```powershell
# Start workers without Beat, so nothing is scheduled automatically.
powershell -ExecutionPolicy Bypass -File .\scripts\start_celery_runtime.ps1 -NoBeat

# Start only collector worker for diagnostics.
powershell -ExecutionPolicy Bypass -File .\scripts\start_celery_runtime.ps1 -NoBeat -NoEnrichment -NoProcessing

# Skip Docker infrastructure start if it is already running.
powershell -ExecutionPolicy Bypass -File .\scripts\start_celery_runtime.ps1 -NoInfrastructure
```

Check local runtime status and queues:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\celery_runtime_status.ps1
```

Stop local runtime:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_celery_runtime.ps1
```

### Docker Worker Profile (Experimental)

The default infrastructure command still starts only PostgreSQL, Redis and Qdrant:

```powershell
docker compose up -d
```

The `workers` profile exists, but do not use it on a low-disk local machine yet:

```powershell
docker compose --profile workers up -d --build
```

Warning: this currently builds worker images from the full `requirements.txt`.
On Linux Docker this can pull and unpack heavy ML packages, especially `torch`
and transformer dependencies. For production, split the image by role first:
light ingestion/beat dependencies separately from the heavy processing image.

### Queue Inspection And Explicit Purge

Inspect queues before purging anything:

```powershell
python scripts\inspect_celery_queues.py --limit 5
```

If a queue contains confirmed stale test tasks, purge that single queue explicitly:

```powershell
python scripts\purge_celery_queue.py --queue enrichment_queue --yes
```

Do not purge queues automatically during normal startup.

### Runtime Smoke Check

After starting workers and Beat:

```powershell
.\.venv\Scripts\celery -A jarvis.ingestion.tasks.celery_app inspect ping
python scripts\inspect_celery_queues.py --limit 3
python -m jarvis.ingestion.cli.daily_health_check --dry-run
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
