$Host.UI.RawUI.WindowTitle = "PhoneHub Auto Start"

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "       PHONEHUB AUTO START"
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

$configPath = "$HOME\.phone_remote\config.json"

if (!(Test-Path $configPath)) {
    Write-Host "Config missing: $configPath" -ForegroundColor Red
    pause
    exit
}

$config = Get-Content $configPath | ConvertFrom-Json
$remote = "$($config.phone_ip):$($config.adb_port)"
$usb = "$($config.usb_serial)"

Write-Host "Phone target: $remote"
Write-Host ""

Write-Host "Starting ADB..."
adb start-server | Out-Host

Write-Host ""
Write-Host "Checking devices..."
$devices = adb devices

if ($devices -match "$remote\s+device") {
    Write-Host "Remote phone already connected." -ForegroundColor Green
}
else {
    Write-Host "Remote not ready. Trying connect..."
    adb connect $remote | Out-Host
    Start-Sleep -Seconds 1

    $devices = adb devices

    if ($devices -match "$remote\s+device") {
        Write-Host "Remote connected." -ForegroundColor Green
    }
    elseif ($devices -match "$usb\s+device") {
        Write-Host "USB phone found. Enabling remote mode..." -ForegroundColor Yellow
        adb -s $usb tcpip 5555 | Out-Host
        Start-Sleep -Seconds 2
        adb connect $remote | Out-Host
    }
    else {
        Write-Host ""
        Write-Host "Phone not connected." -ForegroundColor Red
        Write-Host "Simple fix:"
        Write-Host "1. Connect phone USB"
        Write-Host "2. Unlock phone"
        Write-Host "3. Allow USB debugging if asked"
        Write-Host "4. Run START_PHONEHUB again"
        Write-Host ""
        pause
        exit
    }
}

Write-Host ""
Write-Host "Opening PhoneHub..." -ForegroundColor Green
python C:\PhoneHub\PhoneHub.py
