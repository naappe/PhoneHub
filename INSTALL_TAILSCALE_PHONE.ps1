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

$searchRoots = @(
    (Join-Path $PSScriptRoot "runtime\tailscale"),
    $PSScriptRoot
)

$localApk = $null
foreach ($root in $searchRoots) {
    if (Test-Path $root) {
        $candidate = Get-ChildItem -Path $root -Filter "*tailscale*.apk" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($null -ne $candidate) {
            $localApk = $candidate.FullName
            break
        }
    }
}

if ($null -eq $localApk) {
    throw "No local Tailscale APK was found in the PhoneHub folder. Put the APK under C:\PhoneHub\runtime\tailscale or C:\PhoneHub."
}

Write-Host "[PhoneHub] Using local Tailscale APK:" -ForegroundColor Green
Write-Host "  $localApk" -ForegroundColor White
$tmp = $localApk

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
