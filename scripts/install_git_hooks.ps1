# Install Git hooks for Automated Regression Testing (IR-021, TC-021)
# - pre-commit: runs the regression suite on every commit, so it works without a git remote
# - pre-push:   runs it again before pushing, when a remote exists

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$GitHooksDir = Join-Path $ProjectRoot ".git\hooks"

if (-not (Test-Path $GitHooksDir)) {
    Write-Error ".git/hooks directory not found. Is this a git repository?"
    exit 1
}

function New-RegressionHook([string]$HookName, [string]$Action) {
    $HookContent = @"
#!/bin/sh
# PLADAZ Automated Regression Hook (IR-021 / TC-021)
echo "Running PLADAZ Automated Regression Suite before $Action..."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "./scripts/run_tests.ps1"
RESULT=`$?
if [ `$RESULT -ne 0 ]; then
    echo "Regression tests failed! $Action aborted."
    exit 1
fi
exit 0
"@
    $HookPath = Join-Path $GitHooksDir $HookName
    [System.IO.File]::WriteAllText($HookPath, $HookContent.Replace("`r`n", "`n"))
    Write-Host "Installed git $HookName hook at: $HookPath" -ForegroundColor Green
}

New-RegressionHook "pre-commit" "commit"
New-RegressionHook "pre-push" "push"

Write-Host "Regression suite will now run automatically before every git commit and push." -ForegroundColor Cyan
