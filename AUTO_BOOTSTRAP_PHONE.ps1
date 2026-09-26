param(
    [string]$ApkPath = (Join-Path $PSScriptRoot "PhoneHub-Agent-6.1.0\PhoneHub-Agent-6.1.0-debug.apk"),
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

function Find-ChildByName {
    param($Folder, [string[]]$Names)
    foreach ($item in @($Folder.Items())) {
        foreach ($name in $Names) {
            if ($item.Name -ieq $name) {
                return $item
            }
        }
    }
    return $null
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " PhoneHub 6.1 - One Click Phone Bootstrap" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

if (!(Test-Path $ApkPath)) {
    Write-Host "[PhoneHub] APK not found:" -ForegroundColor Yellow
    Write-Host "  $ApkPath"
    Write-Host ""
    Write-Host "Extract PhoneHub-Agent-6.1.0.zip into C:\PhoneHub first." -ForegroundColor Yellow
    exit 1
}

# Fast path: if an authorized ADB device is already available, install/update directly.
# ADB is optional; normal PhoneHub operation does not depend on it.
$adb = Get-Command adb -ErrorAction SilentlyContinue
if ($null -ne $adb) {
    $devices = & adb devices 2>$null
    $authorized = @($devices | Select-String -Pattern "\tdevice$")

    if ($authorized.Count -gt 0) {
        $serial = (($authorized[0].ToString() -split "\s+")[0]).Trim()
        $model = (& adb -s $serial shell getprop ro.product.model 2>$null).Trim()
        $android = (& adb -s $serial shell getprop ro.build.version.release 2>$null).Trim()
        Write-Host "[PhoneHub] Authorized Android phone found: $($model)" -ForegroundColor Green
        if ($android) { Write-Host "[PhoneHub] Android: $android" -ForegroundColor DarkGray }
        Write-Host "[PhoneHub] Installing PhoneHub Agent directly..." -ForegroundColor Cyan
        & adb -s $serial install -r "$ApkPath"
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "[PhoneHub] PhoneHub Agent installed/updated successfully." -ForegroundColor Green
            if (-not $NoPause) { pause }
            exit 0
        }
        Write-Host "[PhoneHub] Direct install unavailable. Falling back to USB file transfer..." -ForegroundColor Yellow
    }
}

$shell = New-Object -ComObject Shell.Application
$thisPc = $shell.Namespace(17)
if ($null -eq $thisPc) {
    throw "Unable to access This PC."
}

Write-Host "[PhoneHub] Looking for connected Android phone..." -ForegroundColor Cyan

$phone = $null
$storageItem = $null

# Generic MTP discovery: inspect portable devices and select the first one
# that exposes an Android-style internal storage root. No OEM/model names.
foreach ($item in @($thisPc.Items())) {
    try {
        $folder = $item.GetFolder
        if ($null -eq $folder) { continue }

        $candidateStorage = Find-ChildByName -Folder $folder -Names @(
            "Internal shared storage",
            "Internal storage",
            "Shared internal storage",
            "Phone storage",
            "Internal Storage"
        )

        if ($null -ne $candidateStorage) {
            $phone = $item
            $storageItem = $candidateStorage
            break
        }
    } catch {
        continue
    }
}

if ($null -eq $phone) {
    Write-Host "[PhoneHub] No Android MTP storage found." -ForegroundColor Red
    Write-Host "Connect any Android phone by USB, unlock it, and select File Transfer / MTP." -ForegroundColor Yellow
    exit 2
}

Write-Host "[PhoneHub] Found Android device: $($phone.Name)" -ForegroundColor Green

$phoneFolder = $phone.GetFolder

if ($null -eq $storageItem) {
    Write-Host "[PhoneHub] Internal storage is not visible yet." -ForegroundColor Red
    Write-Host "Unlock the phone and choose File Transfer / MTP." -ForegroundColor Yellow
    exit 3
}

$storageFolder = $storageItem.GetFolder
$downloadItem = Find-ChildByName -Folder $storageFolder -Names @("Download","Downloads")

if ($null -eq $downloadItem) {
    Write-Host "[PhoneHub] Download folder not found." -ForegroundColor Red
    exit 4
}

$downloadFolder = $downloadItem.GetFolder
$sourceDir = Split-Path $ApkPath -Parent
$sourceName = Split-Path $ApkPath -Leaf
$sourceFolder = $shell.Namespace($sourceDir)
$sourceItem = $sourceFolder.ParseName($sourceName)

if ($null -eq $sourceItem) {
    throw "Unable to open APK source file."
}

Write-Host "[PhoneHub] Copying PhoneHub Agent APK to Android Download..." -ForegroundColor Cyan
$downloadFolder.CopyHere($sourceItem, 16)

$deadline = (Get-Date).AddSeconds(30)
$copied = $false
do {
    Start-Sleep -Milliseconds 750
    foreach ($item in @($downloadFolder.Items())) {
        if ($item.Name -ieq $sourceName) {
            $copied = $true
            break
        }
    }
} until ($copied -or (Get-Date) -gt $deadline)

if (!$copied) {
    Write-Host "[PhoneHub] Copy started, but Windows has not confirmed completion yet." -ForegroundColor Yellow
    Write-Host "Check the phone Download folder." -ForegroundColor Yellow
    exit 5
}

Write-Host ""
Write-Host "[PhoneHub] APK copied successfully." -ForegroundColor Green
Write-Host ""
Write-Host "PHONE - ONE FINAL TAP:" -ForegroundColor Cyan
Write-Host "  Files > Downloads > $sourceName > Update / Install" -ForegroundColor White
Write-Host ""
Write-Host "Android requires the final install confirmation when only USB file transfer is available." -ForegroundColor Yellow
Write-Host "After PhoneHub Agent is active, PhoneHub can use the managed update path for future supported updates." -ForegroundColor Green
Write-Host ""
if (-not $NoPause) { pause }
