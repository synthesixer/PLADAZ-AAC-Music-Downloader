# PLADAZ - Automated Regression Testing Script (IR-021, TC-021)
# Runs unit, integration, and fs suites and exits with non-zero on failure.

param (
    [string]$Markers = "unit or integration or fs",
    [switch]$All,
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

$PytestExe = Join-Path $ProjectRoot "venv\Scripts\pytest.exe"
if (-not (Test-Path $PytestExe)) {
    Write-Error "Virtual environment pytest not found at $PytestExe. Run inside project venv."
    exit 1
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  PLADAZ Automated Regression Suite (IR-021 / TC-021)     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

if ($SmokeTest) {
    Write-Host "[1/2] Running PyInstaller Smoke Test..." -ForegroundColor Yellow
    $ExePath = Join-Path $ProjectRoot "dist\PLADAZ\PLADAZ.exe"
    if (Test-Path $ExePath) {
        $proc = Start-Process -FilePath $ExePath -ArgumentList "--smoke-test" -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -ne 0) {
            Write-Error "PLADAZ.exe smoke test failed with exit code $($proc.ExitCode)"
            exit $proc.ExitCode
        }
        Write-Host "  -> PLADAZ.exe Smoke Test PASSED (Exit Code: 0)." -ForegroundColor Green
    } else {
        Write-Host "  -> dist\PLADAZ\PLADAZ.exe not found. Skipping standalone exe smoke test." -ForegroundColor DarkYellow
    }
}

if ($All) {
    Write-Host "Running FULL test suite (excluding live network)..." -ForegroundColor Yellow
    & $PytestExe -v
} else {
    Write-Host "Running regression markers: '$Markers'..." -ForegroundColor Yellow
    & $PytestExe -v -m $Markers
}

$ExitCode = $LASTEXITCODE
if ($ExitCode -eq 0) {
    Write-Host "`n>>> REGRESSION SUITE PASSED (Exit Code: 0) <<<" -ForegroundColor Green
} else {
    Write-Host "`n>>> REGRESSION SUITE FAILED (Exit Code: $ExitCode) <<<" -ForegroundColor Red
}

exit $ExitCode

