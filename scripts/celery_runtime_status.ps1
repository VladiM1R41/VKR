param(
    [int]$QueuePreviewLimit = 3,
    [int]$LogTail = 20
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

function Invoke-LayerCommand {
    param([Parameter(Mandatory = $true)][string[]]$Command)
    $ArgsList = @((Join-Path $Root "scripts\run_with_layer_env.py"), "--") + $Command
    & $Python @ArgsList
}

Set-Location $Root

Write-Host "Celery local runtime processes:" -ForegroundColor Cyan
if (Test-Path $RuntimeDir) {
    $Rows = Get-ChildItem $RuntimeDir -Filter "*.pid" | ForEach-Object {
        $PidValue = Get-Content $_.FullName -ErrorAction SilentlyContinue
        $Process = $null
        if ($PidValue -and "$PidValue".Trim() -match '^\d+$') {
            $Process = Get-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue
        }
        [PSCustomObject]@{
            Name = $_.BaseName
            PID = $PidValue
            Running = [bool]$Process
            CPU = if ($Process) { [math]::Round($Process.CPU, 1) } else { $null }
            WorkingSetMB = if ($Process) { [math]::Round($Process.WorkingSet64 / 1MB, 0) } else { $null }
        }
    }
    if ($Rows) {
        $Rows | Format-Table -AutoSize
    }
    else {
        Write-Host "No pid files found."
    }
}
else {
    Write-Host "No local runtime pid directory found."
}

Write-Host ""
Write-Host "Celery inspect ping:" -ForegroundColor Cyan
Invoke-LayerCommand @($Celery, "-A", "jarvis.ingestion.tasks.celery_app", "inspect", "ping", "--timeout=3")

Write-Host ""
Write-Host "Celery active queues:" -ForegroundColor Cyan
Invoke-LayerCommand @($Celery, "-A", "jarvis.ingestion.tasks.celery_app", "inspect", "active_queues", "--timeout=3")

Write-Host ""
Write-Host "Redis queue lengths and previews:" -ForegroundColor Cyan
Invoke-LayerCommand @($Python, (Join-Path $Root "scripts\inspect_celery_queues.py"), "--limit", ([string]$QueuePreviewLimit))

Write-Host ""
Write-Host "Recent runtime logs:" -ForegroundColor Cyan
if (Test-Path $LogDir) {
    Get-ChildItem $LogDir -Filter "celery-*.log" | Sort-Object LastWriteTime -Descending | ForEach-Object {
        Write-Host ""
        Write-Host $_.Name -ForegroundColor Yellow
        Get-Content $_.FullName -Tail $LogTail -ErrorAction SilentlyContinue
    }
}
