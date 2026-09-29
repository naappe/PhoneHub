param(
    [string]$Serial = "",
    [switch]$KeepInstalled
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pkg = "com.phonehub.companion"

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    throw "adb not found."
}

$devices = @(& adb devices | Select-Object -Skip 1 | ForEach-Object {
    if ($_ -match '^([^\s]+)\s+device\s*$') { $matches[1] }
})

if (-not $Serial) {
    $usb = @($devices | Where-Object { $_ -notmatch ':\d+$' })
    if ($usb.Count -eq 1) { $Serial = $usb[0] }
    elseif ($devices.Count -eq 1) { $Serial = $devices[0] }
    else {
        Write-Host "Connected Android targets:"
        for ($i=0; $i -lt $devices.Count; $i++) { Write-Host " [$($i+1)] $($devices[$i])" }
        $choice = [int](Read-Host "Select the physical phone number")
        if ($choice -lt 1 -or $choice -gt $devices.Count) { throw "Invalid device selection." }
        $Serial = $devices[$choice-1]
    }
}

Write-Host "Using device: $Serial"

$manufacturer = (& adb -s $Serial shell getprop ro.product.manufacturer).Trim()
$model = (& adb -s $Serial shell getprop ro.product.model).Trim()
$android = (& adb -s $Serial shell getprop ro.build.version.release).Trim()
$sdk = (& adb -s $Serial shell getprop ro.build.version.sdk).Trim()
$build = (& adb -s $Serial shell getprop ro.build.fingerprint).Trim()
$androidId = (& adb -s $Serial shell settings get secure android_id).Trim()

$safeModel = ($model -replace '[^A-Za-z0-9._-]','_')
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Out = Join-Path $Root ("phone-baselines\{0}-{1}" -f $safeModel,$stamp)
New-Item -ItemType Directory -Force -Path $Out | Out-Null

@"
PhoneHub Android Baseline
=========================
Manufacturer: $manufacturer
Model: $model
Android: $android
SDK: $sdk
Android ID: $androidId
Serial: $Serial
Build fingerprint: $build
Captured: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
"@ | Set-Content (Join-Path $Out "device-info.txt") -Encoding UTF8

& adb -s $Serial shell dumpsys package $Pkg |
    Set-Content (Join-Path $Out "companion-package-dump.txt") -Encoding UTF8

& adb -s $Serial shell pm list permissions -g -f |
    Set-Content (Join-Path $Out "android-permissions.txt") -Encoding UTF8

$paths = @(& adb -s $Serial shell pm path $Pkg | ForEach-Object {
    if ($_ -match '^package:(.+)$') { $matches[1].Trim() }
})

if ($paths.Count -eq 0) {
    throw "PhoneHub Companion is not installed on $Serial."
}

$apkDir = Join-Path $Out "installed-apk"
New-Item -ItemType Directory -Force -Path $apkDir | Out-Null

for ($i=0; $i -lt $paths.Count; $i++) {
    $remote = $paths[$i]
    $name = Split-Path $remote -Leaf
    if ([string]::IsNullOrWhiteSpace($name)) { $name = "split-$i.apk" }
    $local = Join-Path $apkDir $name
    Write-Host "Pulling $remote"
    & adb -s $Serial pull $remote $local
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull $remote" }
}

& adb -s $Serial shell dumpsys battery |
    Set-Content (Join-Path $Out "battery.txt") -Encoding UTF8
& adb -s $Serial shell wm size |
    Set-Content (Join-Path $Out "display.txt") -Encoding UTF8
& adb -s $Serial shell getprop |
    Set-Content (Join-Path $Out "getprop.txt") -Encoding UTF8

Write-Host ""
Write-Host "Baseline saved to:"
Write-Host "  $Out"

if (-not $KeepInstalled) {
    Write-Host ""
    Write-Host "Removing PhoneHub Companion from phone..."
    & adb -s $Serial uninstall $Pkg
    if ($LASTEXITCODE -ne 0) { throw "Companion uninstall failed." }

    $pairFile = Join-Path $HOME ".phonehub\paired_devices.json"
    if (Test-Path $pairFile) {
        try {
            $raw = Get-Content $pairFile -Raw
            $pairsObj = $raw | ConvertFrom-Json
            $pairs = @{}
            if ($pairsObj) {
                $pairsObj.PSObject.Properties | ForEach-Object {
                    $pairs[$_.Name] = $_.Value
                }
            }
            if ($pairs.ContainsKey($androidId)) {
                $pairs.Remove($androidId)
                $pairs | ConvertTo-Json -Depth 10 | Set-Content $pairFile -Encoding UTF8
                Write-Host "Removed stale PC pairing record for this phone."
            }
        } catch {
            Write-Host "Pairing cache was not changed: $($_.Exception.Message)"
        }
    }
}

Write-Host ""
Write-Host "Done."
Write-Host "The phone baseline and exact installed APK files are preserved on the PC."
