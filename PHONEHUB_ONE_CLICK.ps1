param(
    [switch]$SkipPull,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "========================================"
Write-Host " PhoneHub 7 - One Click Update"
Write-Host " Simple phone | Powerful PC"
Write-Host "========================================"

if (-not $SkipPull) {
    Write-Host "[1/5] Updating project from GitHub..."
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "Git update failed. Local work may need attention." }
} else {
    Write-Host "[1/5] Git update skipped."
}

Write-Host "[2/5] Building current Companion..."
& (Join-Path $Root "BUILD_PHONEHUB_V7.ps1")

if (-not $SkipInstall) {
    Write-Host "[3/5] Installing/upgrading Companion..."
    & (Join-Path $Root "INSTALL_PHONEHUB_V7.ps1")
} else {
    Write-Host "[3/5] Companion install skipped."
}

Write-Host "[4/5] Verifying project state..."
$versionLine = Select-String -Path (Join-Path $Root "companion\build.gradle.kts") -Pattern 'versionName\s*=\s*"([^"]+)"' | Select-Object -First 1
$version = if ($versionLine -and $versionLine.Matches.Count) { $versionLine.Matches[0].Groups[1].Value } else { "unknown" }
Write-Host "PhoneHub Companion version: $version"
Write-Host "Git commit: $(& git rev-parse --short HEAD)"

Write-Host "[5/5] Starting PC Control Center..."
Start-Process -FilePath (Join-Path $Root "RUN_PHONEHUB_V7.bat")
Write-Host ""
Write-Host "PhoneHub is ready. Manage the phone from the PC Control Center."
