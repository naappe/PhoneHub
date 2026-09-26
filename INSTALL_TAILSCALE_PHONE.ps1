$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " PhoneHub - Auto Install Tailscale to Phone" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$adb = Get-Command adb -ErrorAction SilentlyContinue
if ($null -eq $adb) {
    throw "ADB is not available."
}

$devices = & adb devices
$deviceLine = @($devices | Select-String -Pattern "\tdevice$") | Select-Object -First 1
if ($null -eq $deviceLine) {
    throw "No authorized Android phone found."
}

$serial = (($deviceLine.ToString() -split "\s+")[0]).Trim()
Write-Host "[PhoneHub] Phone authorized: $serial" -ForegroundColor Green

$stable = "https://pkgs.tailscale.com/stable/"
Write-Host "[PhoneHub] Finding latest official Tailscale APK..." -ForegroundColor Cyan
$page = (Invoke-WebRequest -UseBasicParsing -Uri $stable).Content

$match = [regex]::Match($page, 'href=["'']([^"'']*tailscale-android-universal-([0-9.]+)\.apk)["'']')
if (-not $match.Success) {
    throw "Official Tailscale Android APK was not found."
}

$rel = $match.Groups[1].Value
$version = $match.Groups[2].Value
$apkUrl = if ($rel -match '^https?://') { $rel } else { ([uri]::new([uri]$stable, $rel)).AbsoluteUri }
$shaUrl = "$apkUrl.sha256"

$tmp = Join-Path $env:TEMP "phonehub-tailscale-$version.apk"

Write-Host "[PhoneHub] Downloading Tailscale $version..." -ForegroundColor Cyan
Invoke-WebRequest -UseBasicParsing -Uri $apkUrl -OutFile $tmp

Write-Host "[PhoneHub] Verifying SHA-256..." -ForegroundColor Cyan
$expected = ((Invoke-WebRequest -UseBasicParsing -Uri $shaUrl).Content.Trim() -split "\s+")[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $tmp).Hash.ToLowerInvariant()

if ($actual -ne $expected) {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    throw "Tailscale checksum verification failed."
}

Write-Host "[PhoneHub] Installing Tailscale to phone..." -ForegroundColor Cyan
& adb -s $serial install -r $tmp
if ($LASTEXITCODE -ne 0) {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    throw "Tailscale APK installation failed."
}

Remove-Item $tmp -Force -ErrorAction SilentlyContinue

Write-Host "[PhoneHub] Starting Tailscale..." -ForegroundColor Cyan
& adb -s $serial shell monkey -p com.tailscale.ipn 1 | Out-Null

Write-Host ""
Write-Host "[PhoneHub] Tailscale installed and opened successfully." -ForegroundColor Green
Write-Host "Approve VPN/sign-in on the phone if Android asks." -ForegroundColor Yellow
