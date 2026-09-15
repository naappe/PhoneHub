$Host.UI.RawUI.WindowTitle = "PhoneHub USB Tailscale Setup"

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  PHONEHUB USB TAILSCALE SETUP"
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

cd C:\PhoneHub

$apk = (Get-ChildItem "C:\PhoneHub\apps\*.apk" | Select-Object -First 1).FullName

if (!$apk -or !(Test-Path $apk)) {
    Write-Host "ERROR: APK not found:" -ForegroundColor Red
    Write-Host $apk
    pause
    exit
}

adb start-server | Out-Host

$devices = adb devices

$usbLine = $devices -split "`n" | Where-Object {
    ($_ -match "device$") -and ($_ -notmatch ":5555") -and ($_ -notmatch "List of devices")
} | Select-Object -First 1

if (!$usbLine) {
    Write-Host ""
    Write-Host "No USB phone found." -ForegroundColor Red
    Write-Host "Connect phone USB, unlock phone, allow USB debugging, then run again."
    pause
    exit
}

$serial = ($usbLine -split "\s+")[0]

$model = adb -s $serial shell getprop ro.product.model
$android = adb -s $serial shell getprop ro.build.version.release
$model = $model.Trim()
$android = $android.Trim()

Write-Host ""
Write-Host "Phone found: $model"
Write-Host "Serial: $serial"
Write-Host "Android: $android"
Write-Host ""

$installedCheck = (& adb -s $serial shell pm list packages com.tailscale.ipn 2>&1) -join "`n"

if ($installedCheck -match "com.tailscale.ipn") {
    Write-Host "Tailscale already installed. Skipping APK install." -ForegroundColor Green
} else {
    Write-Host "Installing Tailscale APK automatically..." -ForegroundColor Yellow

    $installText = (& adb -s $serial install -r -g "$apk" 2>&1) -join "`n"
    Write-Host $installText

    Start-Sleep -Seconds 2
    $installedCheck = (& adb -s $serial shell pm list packages com.tailscale.ipn 2>&1) -join "`n"

    if ($installedCheck -notmatch "com.tailscale.ipn") {
        Write-Host "Tailscale install failed. APK was not found on phone after install." -ForegroundColor Red
        pause
        exit
    }

    Write-Host "Tailscale installed." -ForegroundColor Green
} -ForegroundColor Green

Write-Host "Opening Tailscale..."
adb -s $serial shell cmd package resolve-activity --brief com.tailscale.ipn | Out-Host
adb -s $serial shell monkey -p com.tailscale.ipn -c android.intent.category.LAUNCHER 1 | Out-Host

Start-Sleep -Seconds 2

Write-Host ""
Write-Host "NOW DO THIS ON PHONE:" -ForegroundColor Yellow
Write-Host "1. Login to Tailscale"
Write-Host "2. Tap Allow / OK for VPN"
Write-Host "3. Wait until it says Connected"
Write-Host ""

Read-Host "After Tailscale is connected, press ENTER here"

Write-Host ""
Write-Host "Enabling remote ADB..."
adb -s $serial tcpip 5555 | Out-Host
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "Tailscale devices:"
tailscale status | Out-Host

Write-Host ""
$ip = Read-Host "Paste this phone Tailscale IP"

if (!$ip) {
    Write-Host "No IP entered. Cancelled." -ForegroundColor Red
    pause
    exit
}

$remote = "$ip`:5555"

Write-Host ""
Write-Host "Connecting remote ADB..."
adb connect $remote | Out-Host

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

$phoneData = [PSCustomObject]@{
    id = $serial
    label = $model
    device_name = $model
    phone_ip = $ip
    adb_port = 5555
    usb_serial = $serial
    android = $android
}

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

$newPhones += $phoneData

$final = [PSCustomObject]@{
    active_id = $serial
    phones = $newPhones
}

$final | ConvertTo-Json -Depth 10 | Set-Content $phonesFile -Encoding UTF8

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "You can remove USB after PhoneHub shows connected."
Write-Host ""

python C:\PhoneHub\PhoneHub.py



