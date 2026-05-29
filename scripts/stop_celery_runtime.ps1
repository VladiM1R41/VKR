param(
    [switch]$Force,
    [int]$GraceSeconds = 10
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeDir = Join-Path $Root ".tmp\celery_runtime"

if (-not (Test-Path $RuntimeDir)) {
    Write-Host "No local Celery runtime pid directory found."
    exit 0
}

$PidFiles = Get-ChildItem $RuntimeDir -Filter "*.pid"
if (-not $PidFiles) {
    Write-Host "No local Celery runtime pid files found."
    exit 0
}

foreach ($PidFile in $PidFiles) {
    $Name = $PidFile.BaseName
    $PidValue = Get-Content $PidFile.FullName -ErrorAction SilentlyContinue
    if (-not $PidValue -or -not ("$PidValue".Trim() -match '^\d+$')) {
        Set-Content -Path $PidFile.FullName -Value ""
        continue
    }

    $Process = Get-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue
    if ($null -eq $Process) {
        Write-Host "$Name is not running; removing stale pid file."
        Set-Content -Path $PidFile.FullName -Value ""
        continue
    }

    Write-Host "Stopping $Name with PID $PidValue"
    Stop-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue
}

if (-not $Force) {
    $Deadline = (Get-Date).AddSeconds($GraceSeconds)
    while ((Get-Date) -lt $Deadline) {
        $StillRunning = @()
        foreach ($PidFile in $PidFiles) {
            if (-not (Test-Path $PidFile.FullName)) {
                continue
            }
            $PidValue = Get-Content $PidFile.FullName -ErrorAction SilentlyContinue
            if ($PidValue -and "$PidValue".Trim() -match '^\d+$' -and (Get-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue)) {
                $StillRunning += $PidValue
            }
        }
        if (-not $StillRunning) {
            break
        }
        Start-Sleep -Seconds 1
    }
}

foreach ($PidFile in $PidFiles) {
    if (-not (Test-Path $PidFile.FullName)) {
        continue
    }
    $PidValue = Get-Content $PidFile.FullName -ErrorAction SilentlyContinue
    $Process = $null
    if ($PidValue -and "$PidValue".Trim() -match '^\d+$') {
        $Process = Get-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue
    }

    if ($Process -and $Force) {
        Write-Host "Force stopping $($PidFile.BaseName) with PID $PidValue"
        Stop-Process -Id ([int]$PidValue) -Force -ErrorAction SilentlyContinue
        Set-Content -Path $PidFile.FullName -Value ""
    }
    elseif ($Process) {
        Write-Host "$($PidFile.BaseName) is still running; re-run with -Force if needed." -ForegroundColor Yellow
    }
    else {
        Set-Content -Path $PidFile.FullName -Value ""
    }
}

Write-Host "Local Celery runtime stop requested."
