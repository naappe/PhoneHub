$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " ANDROIDBRIDGE PHONE READINESS CHECK" -ForegroundColor Cyan
Write-Host " Read-only: no disconnect / no ADB reset" -ForegroundColor DarkGray
Write-Host "==============================================" -ForegroundColor Cyan

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    Write-Host "ADB NOT FOUND" -ForegroundColor Red
    exit 1
}

$rows = @(adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\sdevice\s*$" })
if (-not $rows) {
    Write-Host "NO AUTHORIZED PHONE FOUND" -ForegroundColor Red
    Write-Host "Connect the Samsung by USB, unlock it, and accept the USB debugging prompt if shown."
    exit 2
}

$serials = @($rows | ForEach-Object { ($_ -split "\s+")[0] })
$usb = @($serials | Where-Object { $_ -notmatch ":" })
if ($usb.Count -gt 0) { $PHONE = $usb[0] } else { $PHONE = $serials[0] }

function ADBShell([string]$Command) {
    $out = & adb -s $PHONE shell $Command 2>&1
    return (($out | Out-String).Trim())
}

function ShowCheck([string]$Name, [string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { $Value = "(no output)" }
    Write-Host ("{0,-28}: {1}" -f $Name, $Value)
}

Write-Host ""
ShowCheck "Selected device" $PHONE
ShowCheck "Model" (ADBShell "getprop ro.product.model")
ShowCheck "Android" (ADBShell "getprop ro.build.version.release")
ShowCheck "SDK" (ADBShell "getprop ro.build.version.sdk")
ShowCheck "Boot completed" (ADBShell "getprop sys.boot_completed")
ShowCheck "Location enabled" (ADBShell "settings get secure location_mode")
ShowCheck "ADB TCP port" (ADBShell "getprop service.adb.tcp.port")
ShowCheck "Wireless debugging" (ADBShell "settings get global adb_wifi_enabled")

Write-Host ""
Write-Host "--- AndroidBridge Companion ---" -ForegroundColor Yellow
$bridgePkg = "com.androidbridge.calls"
$bridgePath = ADBShell "pm path $bridgePkg"
ShowCheck "Installed" $(if ($bridgePath -match "^package:") { "YES" } else { "NO" })

if ($bridgePath -match "^package:") {
    $perm = ADBShell "dumpsys package $bridgePkg"
    $fine = if ($perm -match "android.permission.ACCESS_FINE_LOCATION: granted=true") { "GRANTED" } else { "NOT GRANTED" }
    $coarse = if ($perm -match "android.permission.ACCESS_COARSE_LOCATION: granted=true") { "GRANTED" } else { "NOT GRANTED" }
    $background = if ($perm -match "android.permission.ACCESS_BACKGROUND_LOCATION: granted=true") { "GRANTED" } else { "NOT GRANTED" }
    $camera = if ($perm -match "android.permission.CAMERA: granted=true") { "GRANTED" } else { "NOT GRANTED" }
    $mic = if ($perm -match "android.permission.RECORD_AUDIO: granted=true") { "GRANTED" } else { "NOT GRANTED" }
    $post = if ($perm -match "android.permission.POST_NOTIFICATIONS: granted=true") { "GRANTED" } else { "NOT GRANTED / NOT REQUIRED" }

    ShowCheck "Precise location" $fine
    ShowCheck "Coarse location" $coarse
    ShowCheck "Background location" $background
    ShowCheck "Camera" $camera
    ShowCheck "Microphone" $mic
    ShowCheck "Notifications" $post

    $wl = ADBShell "cmd deviceidle whitelist"
    ShowCheck "Battery whitelist" $(if ($wl -match [regex]::Escape($bridgePkg)) { "YES" } else { "NO" })
    ShowCheck "Standby bucket" (ADBShell "am get-standby-bucket $bridgePkg")

    $svc = ADBShell "dumpsys activity services $bridgePkg"
    ShowCheck "Offline GPS service" $(if ($svc -match "OfflineLocationService") { "RUNNING" } else { "NOT RUNNING" })

    $notif = ADBShell "settings get secure enabled_notification_listeners"
    ShowCheck "Notification listener" $(if ($notif -match [regex]::Escape($bridgePkg)) { "ENABLED" } else { "NOT ENABLED" })
}

Write-Host ""
Write-Host "--- Tailscale ---" -ForegroundColor Yellow
$tailPkg = "com.tailscale.ipn"
$tailPath = ADBShell "pm path $tailPkg"
ShowCheck "Installed" $(if ($tailPath -match "^package:") { "YES" } else { "NO" })
if ($tailPath -match "^package:") {
    $wl = ADBShell "cmd deviceidle whitelist"
    ShowCheck "Battery whitelist" $(if ($wl -match [regex]::Escape($tailPkg)) { "YES" } else { "NO" })
    ShowCheck "Standby bucket" (ADBShell "am get-standby-bucket $tailPkg")
}

Write-Host ""
Write-Host "--- Current ADB routes (read-only) ---" -ForegroundColor Yellow
adb devices -l

Write-Host ""
Write-Host "CHECK COMPLETE" -ForegroundColor Green
Write-Host "Copy everything from ANDROIDBRIDGE PHONE READINESS CHECK to CHECK COMPLETE and send it to ChatGPT."
