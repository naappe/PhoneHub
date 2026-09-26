$ErrorActionPreference = "Stop"

$mutex = New-Object System.Threading.Mutex($false, "PhoneHubTailscaleInstall")
$hasMutex = $false

try {
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) {
        throw "Another PhoneHub Tailscale installation is already running."
    }

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

$installedPath = & adb -s $serial shell pm path com.tailscale.ipn 2>$null
if ($LASTEXITCODE -eq 0 -and ($installedPath -match "package:")) {
    Write-Host "[PhoneHub] Tailscale is already installed on the phone." -ForegroundColor Green
    Write-Host "[PhoneHub] Opening Tailscale..." -ForegroundColor Cyan
    & adb -s $serial shell monkey -p com.tailscale.ipn 1 | Out-Null
    Write-Host "[PhoneHub] Tailscale already installed and opened successfully." -ForegroundColor Green
    exit 0
}

$stable = "https://pkgs.tailscale.com/stable/"
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue

Write-Host "[PhoneHub] Finding latest official Tailscale APK..." -ForegroundColor Cyan
if ($null -ne $curl) {
    $page = (& curl.exe -L --fail --silent --show-error --connect-timeout 10 --max-time 30 $stable) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Could not read Tailscale stable package list." }
} else {
    $page = (Invoke-WebRequest -UseBasicParsing -Uri $stable -TimeoutSec 30).Content
}

$match = [regex]::Match($page, 'href=["'']([^"'']*tailscale-android-universal-([0-9.]+)\.apk)["'']')
if (-not $match.Success) {
    throw "Official Tailscale Android APK was not found."
}

$rel = $match.Groups[1].Value
$version = $match.Groups[2].Value
$apkUrl = if ($rel -match '^https?://') { $rel } else { ([uri]::new([uri]$stable, $rel)).AbsoluteUri }
$shaUrl = "$apkUrl.sha256"

$cacheDir = Join-Path $PSScriptRoot "runtime\tailscale"
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
$cacheApk = Join-Path $cacheDir ("tailscale-android-universal-{0}.apk" -f $version)
$tmp = $cacheApk

Write-Host "[PhoneHub] Getting official SHA-256..." -ForegroundColor Cyan
if ($null -ne $curl) {
    $shaText = (& curl.exe -L --fail --silent --show-error --connect-timeout 10 --max-time 30 $shaUrl) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Could not download Tailscale SHA-256 file." }
    $expected = (($shaText.Trim() -split "\s+")[0]).ToLowerInvariant()
} else {
    $expected = ((Invoke-WebRequest -UseBasicParsing -Uri $shaUrl -TimeoutSec 30).Content.Trim() -split "\s+")[0].ToLowerInvariant()
}

$useCache = $false
if (Test-Path $cacheApk) {
    $cachedHash = (Get-FileHash -Algorithm SHA256 $cacheApk).Hash.ToLowerInvariant()
    if ($cachedHash -eq $expected) {
        $useCache = $true
        Write-Host "[PhoneHub] Using verified cached Tailscale APK from PhoneHub folder." -ForegroundColor Green
    } else {
        Remove-Item $cacheApk -Force -ErrorAction SilentlyContinue
    }
}

if (-not $useCache) {
    Write-Host "[PhoneHub] Downloading Tailscale $version once..." -ForegroundColor Cyan
    $part = "$cacheApk.part"
    Remove-Item $part -Force -ErrorAction SilentlyContinue

    if ($null -ne $curl) {
        & curl.exe -L --fail --show-error --connect-timeout 10 --max-time 180 --retry 2 --retry-delay 1 -o $part $apkUrl
        if ($LASTEXITCODE -ne 0) {
            Remove-Item $part -Force -ErrorAction SilentlyContinue
            throw "Tailscale APK download failed."
        }
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $apkUrl -OutFile $part -TimeoutSec 180
    }

    Move-Item -Force $part $cacheApk
}

Write-Host "[PhoneHub] Verifying SHA-256..." -ForegroundColor Cyan
$actual = (Get-FileHash -Algorithm SHA256 $cacheApk).Hash.ToLowerInvariant()

if ($actual -ne $expected) {
    Remove-Item $cacheApk -Force -ErrorAction SilentlyContinue
    throw "Tailscale checksum verification failed."
}

Write-Host "[PhoneHub] Installing Tailscale to phone..." -ForegroundColor Cyan
& adb -s $serial install -r $tmp
if ($LASTEXITCODE -ne 0) {
    throw "Tailscale APK installation failed."
}

Write-Host "[PhoneHub] Starting Tailscale..." -ForegroundColor Cyan
& adb -s $serial shell monkey -p com.tailscale.ipn 1 | Out-Null

Write-Host ""
Write-Host "[PhoneHub] Tailscale installed and opened successfully." -ForegroundColor Green
Write-Host "Approve VPN/sign-in on the phone if Android asks." -ForegroundColor Yellow
}
finally {
    if ($hasMutex) {
        $mutex.ReleaseMutex() | Out-Null
    }
    $mutex.Dispose()
}
