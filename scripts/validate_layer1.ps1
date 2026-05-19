param(
    [switch]$FullUnit,
    [switch]$SkipUnit,
    [switch]$SkipHealth,
    [switch]$CheckDocker,
    [switch]$ApplyMigrations,
    [switch]$LiveSmoke,
    [switch]$LiveAllSources,
    [string[]]$SmokeSources = @(),
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = "src"
$Failures = New-Object System.Collections.Generic.List[string]

function Invoke-ValidationStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    try {
        $global:LASTEXITCODE = 0
        & $Command
        if ($LASTEXITCODE -ne 0) {
            throw "Command exited with code $LASTEXITCODE"
        }
        Write-Host "OK: $Name" -ForegroundColor Green
    }
    catch {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        $Failures.Add($Name) | Out-Null
        if ($Strict) {
            throw
        }
    }
}

Set-Location $Root
Write-Host "Layer 1 validation"
Write-Host "Root: $Root"
Write-Host "Python: $Python"

if ($ApplyMigrations) {
    Invoke-ValidationStep "Alembic upgrade head" {
        & $Python -m alembic upgrade head
    }
}
else {
    Invoke-ValidationStep "Alembic current" {
        & $Python -m alembic current
    }
}

if ($CheckDocker) {
    Invoke-ValidationStep "Docker containers" {
        docker ps --format "table {{.Names}}\t{{.Status}}"
    }
}

if (-not $SkipUnit) {
    $Layer1Tests = @(
        "tests/unit/test_layer1_regressions.py",
        "tests/unit/test_health.py",
        "tests/unit/test_health_report.py",
        "tests/unit/test_monitoring.py",
        "tests/unit/test_collect_source_conditional.py",
        "tests/unit/test_collect_source_lock.py",
        "tests/unit/test_enrich_source_delay.py",
        "tests/unit/test_rss_collector.py",
        "tests/unit/test_rss_collector_flow.py",
        "tests/unit/test_rss_collector_source_keys.py",
        "tests/unit/test_rss_fulltext.py",
        "tests/unit/test_rss_fulltext_inline.py",
        "tests/unit/test_rss_parser.py",
        "tests/unit/test_aif_rss_collector.py",
        "tests/unit/test_aif_turbo_structured.py",
        "tests/unit/test_dates.py",
        "tests/unit/test_urls.py",
        "tests/unit/test_postprocess.py",
        "tests/unit/test_source_specific.py",
        "tests/unit/test_source_specific_candidates.py",
        "tests/unit/test_http_client.py",
        "tests/unit/test_pubsub.py",
        "tests/unit/test_distributed_lock.py",
        "tests/unit/test_extraction_runtime.py",
        "tests/unit/test_trafilatura_extractor.py",
        "tests/unit/test_scheduler.py",
        "tests/unit/test_celery_tasks.py",
        "tests/unit/test_run_timing.py",
        "tests/unit/test_kommersant_postprocess.py"
    )

    Invoke-ValidationStep "Layer 1 unit tests" {
        & $Python -m pytest @Layer1Tests
    }

    if ($FullUnit) {
        Invoke-ValidationStep "Full unit test suite" {
            & $Python -m pytest tests/unit
        }
    }
}

if (-not $SkipHealth) {
    Invoke-ValidationStep "Health report JSON" {
        & $Python -m jarvis.ingestion.cli.health_report --json
    }

    Invoke-ValidationStep "Daily health check dry-run" {
        & $Python -m jarvis.ingestion.cli.daily_health_check --dry-run
    }
}

if ($LiveSmoke) {
    if ($SmokeSources.Count -eq 0) {
        Invoke-ValidationStep "Live smoke default sources: IDs 1,3" {
            $Code = @'
import json
from sqlalchemy import select
from jarvis.db.models import Source
from jarvis.db.session import SyncSessionLocal
from jarvis.ingestion.services.collect_source import run_collect_source

with SyncSessionLocal() as session:
    source_names = list(
        session.scalars(select(Source.name).where(Source.id.in_([1, 3])).order_by(Source.id))
    )

results = []
for name in source_names:
    try:
        result = run_collect_source(name)
    except Exception as exc:
        result = {"source": name, "status": "exception", "error": str(exc)}
    results.append(result)

print(json.dumps({"sources_total": len(results), "results": results}, ensure_ascii=False, indent=2, default=str))
if any(item.get("status") == "exception" for item in results):
    raise SystemExit(1)
'@
            $Code | & $Python -
        }
    }
    else {
        foreach ($SourceName in $SmokeSources) {
            Invoke-ValidationStep "Live smoke source: $SourceName" {
                & $Python -m jarvis.ingestion.cli.run_source --source $SourceName
            }
        }
    }
}

if ($LiveAllSources) {
    Invoke-ValidationStep "Live all active sources" {
        $Code = @'
import json
from collections import Counter
from sqlalchemy import select
from jarvis.db.models import Source
from jarvis.db.session import SyncSessionLocal
from jarvis.ingestion.services.collect_source import run_collect_source

with SyncSessionLocal() as session:
    source_names = list(session.scalars(select(Source.name).where(Source.is_active.is_(True)).order_by(Source.id)))

results = []
for name in source_names:
    try:
        result = run_collect_source(name)
    except Exception as exc:
        result = {"source": name, "status": "exception", "error": str(exc)}
    results.append(result)

summary = Counter(str(item.get("status")) for item in results)
print(json.dumps({"sources_total": len(results), "summary": dict(summary), "results": results}, ensure_ascii=False, indent=2, default=str))
if any(item.get("status") == "exception" for item in results):
    raise SystemExit(1)
'@
        $Code | & $Python -
    }
}

Write-Host ""
if ($Failures.Count -eq 0) {
    Write-Host "Layer 1 validation completed successfully." -ForegroundColor Green
    exit 0
}

Write-Host "Layer 1 validation completed with failures:" -ForegroundColor Red
foreach ($Failure in $Failures) {
    Write-Host " - $Failure" -ForegroundColor Red
}
exit 1
