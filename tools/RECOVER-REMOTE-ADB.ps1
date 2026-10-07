param(
    [string]$PhoneIP = "100.127.244.20"
)

$ErrorActionPreference = "Stop"
$env:ANDROIDBRIDGE_PHONE_IP = $PhoneIP
$Root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "[AndroidBridge] Verifying Tailscale reachability..." -ForegroundColor Cyan
& tailscale ping --c 1 $PhoneIP
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tailscale cannot currently reach $PhoneIP." -ForegroundColor Red
    exit 2
}

& python (Join-Path $PSScriptRoot "recover_remote_adb.py")
$rc = $LASTEXITCODE

if ($rc -eq 0) {
    Write-Host ""
    Write-Host "[AndroidBridge] Recovery successful." -ForegroundColor Green
    Write-Host "Open AndroidBridge again from the desktop icon." -ForegroundColor Green
}
exit $rc
