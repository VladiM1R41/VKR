param(
    [switch]$NoInfrastructure,
    [switch]$NoBeat,
    [switch]$NoCollector,
    [switch]$NoEnrichment,
    [switch]$NoProcessing,
    [switch]$NoAnalytics,
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeDir = Join-Path $Root ".tmp\celery_runtime"
$LogDir = Join-Path $Root "logs"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Celery = Join-Path $Root ".venv\Scripts\celery.exe"

if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python"
}
if (-not (Test-Path $Celery)) {
    throw "Celery executable not found: $Celery"
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Set-LocalRuntimeEnv {
    $env:PYTHONPATH = "src"
    $env:PROCESSING_EMBEDDING_BACKEND = "flagembedding"
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    $env:CELERY_ENABLE_LAYER4_SCHEDULE = if ($env:CELERY_ENABLE_LAYER4_SCHEDULE) { $env:CELERY_ENABLE_LAYER4_SCHEDULE } else { "false" }

    foreach ($ProxyVar in @(
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "GIT_HTTP_PROXY",
        "GIT_HTTPS_PROXY"
    )) {
        Remove-Item "Env:$ProxyVar" -ErrorAction SilentlyContinue
    }
}

function Invoke-LayerCommand {
    param([Parameter(Mandatory = $true)][string[]]$Command)
    $ArgsList = @((Join-Path $Root "scripts\run_with_layer_env.py"), "--") + $Command
    & $Python @ArgsList
}

function Wait-TcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutSeconds = 90
    )

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        $Client = New-Object System.Net.Sockets.TcpClient
        try {
            $Async = $Client.BeginConnect($HostName, $Port, $null, $null)
            if ($Async.AsyncWaitHandle.WaitOne(1000, $false)) {
                $Client.EndConnect($Async)
                return
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
        finally {
            $Client.Close()
        }
    }

    throw "Timed out waiting for $HostName`:$Port"
}

function Get-RuntimeSettings {
    $Json = Invoke-LayerCommand @(
        $Python,
        "-c",
        "import json; from jarvis.core.settings import get_settings; s=get_settings(); print(json.dumps({'postgres_host':s.postgres_host,'postgres_port':s.postgres_port,'redis_host':s.redis_host,'redis_port':s.redis_port,'qdrant_host':s.qdrant_host,'qdrant_port':s.qdrant_port,'scheduler_tick_seconds':s.scheduler_tick_seconds,'processing_tick_seconds':s.processing_tick_seconds,'processing_batch_size':s.processing_batch_size,'celery_enable_layer4_schedule':s.celery_enable_layer4_schedule}, ensure_ascii=False))"
    )
    return $Json | ConvertFrom-Json
}

function Start-CeleryProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$CeleryArgs
    )

    $PidFile = Join-Path $RuntimeDir "$Name.pid"
    if (Test-Path $PidFile) {
        $ExistingPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($ExistingPid -and (Get-Process -Id ([int]$ExistingPid) -ErrorAction SilentlyContinue)) {
            Write-Host "$Name already running with PID $ExistingPid" -ForegroundColor Yellow
            return
        }
        Set-Content -Path $PidFile -Value ""
    }

    $LogFile = Join-Path $LogDir "$Name.log"
    $FinalCeleryArgs = $CeleryArgs + @("--logfile", $LogFile)
    $Process = Start-Process `
        -FilePath $Celery `
        -ArgumentList $FinalCeleryArgs `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -PassThru

    Set-Content -Path $PidFile -Value $Process.Id
    Write-Host "Started $Name with PID $($Process.Id)" -ForegroundColor Green
    Write-Host "  log: $LogFile"
}

Set-Location $Root
Set-LocalRuntimeEnv

if (-not $NoInfrastructure) {
    Write-Host "Starting infrastructure only: postgres, redis, qdrant" -ForegroundColor Cyan
    docker compose up -d postgres redis qdrant
}
else {
    Write-Host "Skipping Docker infrastructure start." -ForegroundColor Yellow
}

$Settings = Get-RuntimeSettings

Write-Host "Waiting for configured services..." -ForegroundColor Cyan
Wait-TcpPort $Settings.postgres_host ([int]$Settings.postgres_port)
Wait-TcpPort $Settings.redis_host ([int]$Settings.redis_port)
Wait-TcpPort $Settings.qdrant_host ([int]$Settings.qdrant_port)

if (-not $SkipHealthCheck) {
    Write-Host "Running Layer 1 health dry check..." -ForegroundColor Cyan
    Invoke-LayerCommand @($Python, "-m", "jarvis.ingestion.cli.daily_health_check", "--dry-run")
}

Write-Host "Runtime settings:" -ForegroundColor Cyan
$Settings | Format-List

if (-not $NoCollector) {
    Start-CeleryProcess "celery-worker-collector" @(
        "-A", "jarvis.ingestion.tasks.celery_app",
        "worker", "-n", "collector@%h", "-Q", "collector_queue", "-l", "info", "--pool=solo",
        "--without-mingle", "--without-gossip"
    )
}

if (-not $NoEnrichment) {
    Start-CeleryProcess "celery-worker-enrichment" @(
        "-A", "jarvis.ingestion.tasks.celery_app",
        "worker", "-n", "enrichment@%h", "-Q", "enrichment_queue", "-l", "info", "--pool=solo",
        "--without-mingle", "--without-gossip"
    )
}

if (-not $NoProcessing) {
    Start-CeleryProcess "celery-worker-processing" @(
        "-A", "jarvis.ingestion.tasks.celery_app",
        "worker", "-n", "processing@%h", "-Q", "processing_queue", "-l", "info", "--pool=solo",
        "--without-mingle", "--without-gossip"
    )
}

if (-not $NoAnalytics) {
    Start-CeleryProcess "celery-worker-analytics" @(
        "-A", "jarvis.ingestion.tasks.celery_app",
        "worker", "-n", "analytics@%h", "-Q", "analytics_queue", "-l", "info", "--pool=solo",
        "--without-mingle", "--without-gossip"
    )
}

if (-not $NoBeat) {
    Start-CeleryProcess "celery-beat" @(
        "-A", "jarvis.ingestion.tasks.celery_app",
        "beat", "-l", "info", "--schedule", ".tmp\celery_runtime\celerybeat-schedule"
    )
}

Write-Host ""
Write-Host "Local Celery runtime requested." -ForegroundColor Green
Write-Host "Status: .\scripts\celery_runtime_status.ps1"
Write-Host "Stop:   .\scripts\stop_celery_runtime.ps1"
