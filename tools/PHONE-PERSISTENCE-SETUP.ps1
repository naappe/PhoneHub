$ErrorActionPreference = "Continue"
$BridgePkg = "com.androidbridge.calls"
$TailPkg = "com.tailscale.ipn"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " ANDROIDBRIDGE PERSISTENCE SETUP" -ForegroundColor Cyan
Write-Host " Existing apps only - no uninstall / no ADB reset" -ForegroundColor DarkGray
Write-Host "==============================================" -ForegroundColor Cyan

$rows = @(adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\sdevice\s*$" })
$serials = @($rows | ForEach-Object { ($_ -split "\s+")[0] })
$usb = @($serials | Where-Object { $_ -notmatch ":" })
if ($usb.Count -lt 1) {
    Write-Host "USB-authorized phone not found." -ForegroundColor Red
    exit 2
}
$PHONE = $usb[0]
Write-Host ("Phone: " + $PHONE) -ForegroundColor Green

foreach ($pkg in @($BridgePkg,$TailPkg)) {
    adb -s $PHONE shell cmd deviceidle whitelist "+$pkg" | Out-Null
    adb -s $PHONE shell am set-standby-bucket $pkg active | Out-Null
    adb -s $PHONE shell cmd appops set $pkg RUN_IN_BACKGROUND allow | Out-Null
    adb -s $PHONE shell cmd appops set $pkg RUN_ANY_IN_BACKGROUND allow | Out-Null
}

Write-Host "AndroidBridge + Tailscale background persistence applied." -ForegroundColor Green

adb -s $PHONE shell am start -n com.androidbridge.calls/com.androidbridge.OfflineLocationSetupActivity --ez enable_offline_gps true | Out-Null
Start-Sleep -Seconds 2

$wl = (adb -s $PHONE shell cmd deviceidle whitelist | Out-String)
$svc = (adb -s $PHONE shell dumpsys activity services $BridgePkg | Out-String)

Write-Host ""
Write-Host ("AndroidBridge Doze whitelist: " + $(if($wl -match [regex]::Escape($BridgePkg)){"YES"}else{"NO"}))
Write-Host ("Tailscale Doze whitelist:      " + $(if($wl -match [regex]::Escape($TailPkg)){"YES"}else{"NO"}))
Write-Host ("Offline GPS service:          " + $(if($svc -match "OfflineLocationService"){"RUNNING"}else{"NOT RUNNING"}))
Write-Host ""
Write-Host "PERSISTENCE SETUP COMPLETE" -ForegroundColor Green
Write-Host "No adb disconnect or adb kill-server was used." -ForegroundColor DarkGray