param(
    [int]$Port = 5555,
    [string]$Address = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Celery = Join-Path $Root ".venv\Scripts\celery.exe"

if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python"
}
if (-not (Test-Path $Celery)) {
    throw "Celery executable not found: $Celery"
}

$FlowerCheck = & $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flower') else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Flower is not installed. Run: .\.venv\Scripts\python -m pip install flower==2.0.1"
}

Set-Location $Root

$ArgsList = @(
    (Join-Path $Root "scripts\run_with_layer_env.py"),
    "--",
    $Celery,
    "-A",
    "jarvis.ingestion.tasks.celery_app",
    "flower",
    "--address=$Address",
    "--port=$Port"
)

Write-Host "Starting Celery Flower UI..." -ForegroundColor Cyan
Write-Host "URL: http://$Address`:$Port"
Write-Host "Stop Flower with Ctrl+C in this terminal."

& $Python @ArgsList
