$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=============================================="
Write-Host " AndroidBridge - Prepare Offline GPS"
Write-Host "=============================================="
Write-Host ""

Set-Location "C:\AndroidBridge-Lite"

git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    throw "git pull failed"
}

python ".\tools\offline-location\prepare_offline_gps.py"
if ($LASTEXITCODE -ne 0) {
    throw "Offline GPS build failed"
}

Write-Host ""
Write-Host "Phone update prepared locally."
Write-Host "The phone does NOT need Internet to collect GPS after this update is installed."
Write-Host "Because the phone is offline right now, this script does not attempt any ADB reconnect/disconnect."
Write-Host ""
