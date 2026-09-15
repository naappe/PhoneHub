$Host.UI.RawUI.WindowTitle = "PhoneHub New Phone Setup"

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "     PHONEHUB NEW PHONE SETUP"
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

cd C:\PhoneHub

Write-Host "Starting ADB..."
adb start-server | Out-Host

Write-Host ""
Write-Host "Checking USB phone..."
$devices = adb devices

$usbLine = $devices -split "`n" | Where-Object {
    ($_ -match "device$") -and ($_ -notmatch ":5555") -and ($_ -notmatch "List of devices")
} | Select-Object -First 1

if (!$usbLine) {
    Write-Host ""
    Write-Host "No USB phone found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Do this:"
    Write-Host "1. Connect phone by USB"
    Write-Host "2. Unlock phone"
    Write-Host "3. Tap Allow USB debugging"
    Write-Host "4. Run SETUP_NEW_PHONE again"
    Write-Host ""
    exit
}

$serial = ($usbLine -split "\s+")[0]

Write-Host "USB phone found: $serial" -ForegroundColor Green

$model = adb -s $serial shell getprop ro.product.model
$android = adb -s $serial shell getprop ro.build.version.release

$model = $model.Trim()
$android = $android.Trim()

Write-Host ""
Write-Host "Phone : $model"
Write-Host "Android: $android"
Write-Host "Serial : $serial"
Write-Host ""

Write-Host "Enabling remote ADB..."
adb -s $serial tcpip 5555 | Out-Host

Write-Host ""
Write-Host "Checking Tailscale on phone..."
$tailscalePackage = adb -s $serial shell pm list packages com.tailscale.ipn

if ($tailscalePackage -match "com.tailscale.ipn") {
    Write-Host "Tailscale is installed." -ForegroundColor Green
    Write-Host "Opening Tailscale..."
    adb -s $serial shell monkey -p com.tailscale.ipn 1 | Out-Host
}
else {
    Write-Host "Tailscale is not installed." -ForegroundColor Yellow
    Write-Host "Opening Play Store Tailscale page..."
    adb -s $serial shell am start -a android.intent.action.VIEW -d "market://details?id=com.tailscale.ipn" | Out-Host

    Write-Host ""
    Write-Host "Install Tailscale on the phone, login, and allow VPN."
}

Write-Host ""
Write-Host "Now on the phone:"
Write-Host "1. Login to Tailscale"
Write-Host "2. Tap Allow / OK for VPN"
Write-Host "3. Make sure Tailscale says Connected"
Write-Host ""

Write-Host "After Tailscale connects, find the phone IP."
Write-Host ""
Write-Host "Laptop Tailscale status:"
tailscale status | Out-Host

Write-Host ""
$ip = Read-Host "Paste this phone's Tailscale IP here, example 100.118.102.57"

if (!$ip) {
    Write-Host "No IP entered. Setup cancelled." -ForegroundColor Red
    exit
}

$remote = "$ip`:5555"

Write-Host ""
Write-Host "Connecting remote ADB..."
adb connect $remote | Out-Host

$phoneData = @{
    id = $serial
    label = $model
    device_name = $model
    phone_ip = $ip
    adb_port = 5555
    usb_serial = $serial
    android = $android
}

$configDir = "$HOME\.phone_remote"
$configFile = "$configDir\config.json"
$phonesFile = "$configDir\phones.json"

if (!(Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir | Out-Null
}

$config = @{
    phone_ip = $ip
    adb_port = 5555
    device_name = $model
    usb_serial = $serial
}

$config | ConvertTo-Json -Depth 5 | Set-Content $configFile -Encoding UTF8

if (Test-Path $phonesFile) {
    try {
        $phonesJson = Get-Content $phonesFile -Raw | ConvertFrom-Json
    }
    catch {
        $phonesJson = $null
    }
}
else {
    $phonesJson = $null
}

if ($null -eq $phonesJson) {
    $phonesJson = [PSCustomObject]@{
        active_id = $serial
        phones = @()
    }
}

$newPhones = @()

foreach ($p in $phonesJson.phones) {
    if ($p.id -ne $serial) {
        $newPhones += $p
    }
}

$newPhones += [PSCustomObject]$phoneData

$final = [PSCustomObject]@{
    active_id = $serial
    phones = $newPhones
}

$final | ConvertTo-Json -Depth 10 | Set-Content $phonesFile -Encoding UTF8

Write-Host ""
Write-Host "Phone saved to PhoneHub." -ForegroundColor Green
Write-Host "Active phone: $model ($ip)"
Write-Host ""

Write-Host "Opening PhoneHub..."
python C:\PhoneHub\PhoneHub.py
