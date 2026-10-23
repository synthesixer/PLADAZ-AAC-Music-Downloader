# Install Git Pre-Push Hook for Automated Regression Testing (IR-021, TC-021)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$GitHooksDir = Join-Path $ProjectRoot ".git\hooks"

if (-not (Test-Path $GitHooksDir)) {
    Write-Error ".git/hooks directory not found. Is this a git repository?"
    exit 1
}

$HookPath = Join-Path $GitHooksDir "pre-push"
$HookContent = @'
#!/bin/sh
# PLADAZ Automated Regression Hook (IR-021 / TC-021)
echo "Running PLADAZ Automated Regression Suite before push..."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "./scripts/run_tests.ps1"
RESULT=$?
if [ $RESULT -ne 0 ]; then
    echo "Regression tests failed! Push aborted."
    exit 1
fi
exit 0
'@

[System.IO.File]::WriteAllText($HookPath, $HookContent.Replace("`r`n", "`n"))

Write-Host "Successfully installed git pre-push hook at: $HookPath" -ForegroundColor Green
Write-Host "Regression suite will now run automatically before every git push." -ForegroundColor Cyan

