param(
    [string]$Root = "C:\AndroidBridge-Lite"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " ANDROIDBRIDGE - ORGANIZE AND REPAIR" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

if (-not (Test-Path $Root)) {
    throw "AndroidBridge root not found: $Root"
}

# Stop only AndroidBridge's own desktop process and local scrcpy windows.
# Do not disconnect ADB, do not kill the ADB server, and do not change Tailscale.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -like '*AndroidBridge-Lite.py*'
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Get-Process scrcpy -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

Set-Location $Root

Write-Host "[1/5] Updating the one active source tree..."
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    throw "git pull failed. The working tree was not changed further."
}

Write-Host "[2/5] Restoring the canonical runtime files..."
$tracked = @(
    "AndroidBridge-Lite.bat",
    "pc\AndroidBridge-Lite.py",
    "pc\AndroidBridge-PhoneData.py",
    "pc\scrcpy-server-v4.1-llb",
    "pc\scrcpy-server-v4.1-llb.sha256"
)
git restore --source=HEAD --worktree -- $tracked

Write-Host "[3/5] Removing retired generated helpers and stale logs..."
$stale = @(
    "pc\AndroidBridge-AdbProxy.exe",
    "pc\AndroidBridge-AdbProxyV2.exe",
    "pc\AndroidBridge-AdbProxyV2.cs",
    "pc\scrcpy-audio.log",
    "pc\scrcpy-camera.log",
    "pc\scrcpy-screen.log",
    "pc\scrcpy-current.log"
)
foreach ($item in $stale) {
    $full = Join-Path $Root $item
    if (Test-Path $full) {
        Remove-Item $full -Force -ErrorAction SilentlyContinue
    }
}

Get-ChildItem -Path (Join-Path $Root "pc") -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Old root-level Python copies are not runtime files. Preserve rather than
# delete them if they exist, so there is no data loss.
$archive = "C:\AndroidBridge-Archive"
New-Item -ItemType Directory -Path $archive -Force | Out-Null

foreach ($name in @("AndroidBridge-Lite.py", "AndroidBridge-PhoneData.py")) {
    $old = Join-Path $Root $name
    if (Test-Path $old) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        Move-Item $old (Join-Path $archive ($stamp + "-" + $name)) -Force
        Write-Host "      Archived stale root copy: $name"
    }
}

Write-Host "[4/5] Verifying executables and active files..."
$adb = (Get-Command adb -ErrorAction Stop).Source
$scrcpy = (Get-Command scrcpy -ErrorAction Stop).Source
$python = (Get-Command python -ErrorAction Stop).Source

Write-Host "      Python : $python"
Write-Host "      ADB    : $adb"
Write-Host "      scrcpy : $scrcpy"
Write-Host "      App    : $Root\pc\AndroidBridge-Lite.py"

$proxyFiles = Get-ChildItem -Path $Root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "AndroidBridge-AdbProxy*" }

if ($proxyFiles) {
    Write-Warning "Retired proxy files still exist:"
    $proxyFiles | ForEach-Object { Write-Host "      $($_.FullName)" }
} else {
    Write-Host "      Retired ADB proxies: NONE"
}

Write-Host "[5/5] Starting the canonical AndroidBridge..."
Write-Host ""
& (Join-Path $Root "AndroidBridge-Lite.bat")
