param(
    [string]$ProjectRoot = "C:\Project-Archive\AndroidBridge-Calls"
)

$ErrorActionPreference = "Stop"
$Package = "com.androidbridge.calls"
$Phone = "R5CY20RCX8E"
$AndroidNs = "http://schemas.android.com/apk/res/android"

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " SAMSUNG SECURE - PERSISTENT WIRELESS DEBUGGING" -ForegroundColor Cyan
Write-Host " One-time USB setup. No uninstall, no ADB reset, no pairing reset." -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $ProjectRoot)) {
    throw "Mobile project not found: $ProjectRoot"
}

$Manifest = Join-Path $ProjectRoot "app\src\main\AndroidManifest.xml"
$JavaDir = Join-Path $ProjectRoot "app\src\main\java\com\androidbridge"
$Receiver = Join-Path $JavaDir "WirelessDebugBootReceiver.java"

if (-not (Test-Path $Manifest)) {
    throw "AndroidManifest.xml not found: $Manifest"
}

New-Item -ItemType Directory -Path $JavaDir -Force | Out-Null

$receiverSource = @'
package com.androidbridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Settings;
import android.util.Log;

/**
 * Restores Android's secure Wireless Debugging transport after a real reboot.
 *
 * WRITE_SECURE_SETTINGS is granted once by the AndroidBridge installer over
 * the already-authorized USB ADB connection. This receiver never changes USB
 * debugging, ADB keys, pairing records, Tailscale, or network configuration.
 */
public class WirelessDebugBootReceiver extends BroadcastReceiver {
    private static final String TAG = "SamsungSecureAdbBoot";
    private static final String ADB_WIFI_KEY = "adb_wifi_enabled";

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? null : intent.getAction();

        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            return;
        }

        try {
            int current = Settings.Global.getInt(
                    context.getContentResolver(),
                    ADB_WIFI_KEY,
                    0
            );

            if (current != 1) {
                boolean changed = Settings.Global.putInt(
                        context.getContentResolver(),
                        ADB_WIFI_KEY,
                        1
                );
                Log.i(TAG, "Wireless debugging restore requested; changed=" + changed);
            } else {
                Log.i(TAG, "Wireless debugging already enabled");
            }
        } catch (SecurityException e) {
            Log.e(TAG, "WRITE_SECURE_SETTINGS is not granted", e);
        } catch (Exception e) {
            Log.e(TAG, "Unable to restore wireless debugging", e);
        }
    }
}
'@

Write-Utf8NoBom $Receiver $receiverSource
Write-Host "Receiver source: READY" -ForegroundColor Green

# Patch the manifest with the development permission and a private boot receiver.
[xml]$xml = Get-Content $Manifest -Raw
$manifestNode = $xml.manifest
if (-not $manifestNode) {
    throw "Invalid Android manifest."
}

$hasWriteSecure = $false
foreach ($node in @($manifestNode.'uses-permission')) {
    if ($node.GetAttribute("name", $AndroidNs) -eq "android.permission.WRITE_SECURE_SETTINGS") {
        $hasWriteSecure = $true
        break
    }
}

if (-not $hasWriteSecure) {
    $permission = $xml.CreateElement("uses-permission")
    $permission.SetAttribute("name", $AndroidNs, "android.permission.WRITE_SECURE_SETTINGS")
    $appNode = $manifestNode.application
    [void]$manifestNode.InsertBefore($permission, $appNode)
    Write-Host "Manifest permission: ADDED" -ForegroundColor Green
} else {
    Write-Host "Manifest permission: ALREADY PRESENT" -ForegroundColor DarkGray
}

$app = $manifestNode.application
if (-not $app) {
    throw "Manifest has no application element."
}

$receiverNode = $null
foreach ($node in @($app.receiver)) {
    $name = $node.GetAttribute("name", $AndroidNs)
    if ($name -eq "com.androidbridge.WirelessDebugBootReceiver") {
        $receiverNode = $node
        break
    }
}

if (-not $receiverNode) {
    $receiverNode = $xml.CreateElement("receiver")
    $receiverNode.SetAttribute("name", $AndroidNs, "com.androidbridge.WirelessDebugBootReceiver")
    $receiverNode.SetAttribute("enabled", $AndroidNs, "true")
    $receiverNode.SetAttribute("exported", $AndroidNs, "false")

    $filter = $xml.CreateElement("intent-filter")
    foreach ($actionName in @(
        "android.intent.action.BOOT_COMPLETED",
        "android.intent.action.MY_PACKAGE_REPLACED"
    )) {
        $action = $xml.CreateElement("action")
        $action.SetAttribute("name", $AndroidNs, $actionName)
        [void]$filter.AppendChild($action)
    }
    [void]$receiverNode.AppendChild($filter)
    [void]$app.AppendChild($receiverNode)
    Write-Host "Boot receiver: ADDED" -ForegroundColor Green
} else {
    Write-Host "Boot receiver: ALREADY PRESENT" -ForegroundColor DarkGray
}

$settings = New-Object System.Xml.XmlWriterSettings
$settings.Indent = $true
$settings.Encoding = New-Object System.Text.UTF8Encoding($false)
$writer = [System.Xml.XmlWriter]::Create($Manifest, $settings)
try {
    $xml.Save($writer)
} finally {
    $writer.Close()
}

Write-Host ""
Write-Host "[1/4] Building APK..." -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & .\gradlew.bat assembleDebug
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

$Apk = Join-Path $ProjectRoot "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $Apk)) {
    throw "APK not found after build: $Apk"
}

Write-Host ""
Write-Host "[2/4] Checking authorized USB ADB..." -ForegroundColor Cyan
$usbOnline = (adb devices | Out-String) -match ("(?m)^" + [regex]::Escape($Phone) + "\s+device\s*$")
if (-not $usbOnline) {
    throw "USB ADB $Phone is not online. Connect the already-authorized USB cable and run this script again."
}

Write-Host "USB ADB: ONLINE" -ForegroundColor Green

Write-Host ""
Write-Host "[3/4] Installing in place and granting boot restore permission..." -ForegroundColor Cyan
adb -s $Phone install -r $Apk | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "APK update failed. Existing Samsung Secure was NOT uninstalled."
}

adb -s $Phone shell pm grant $Package android.permission.WRITE_SECURE_SETTINGS
if ($LASTEXITCODE -ne 0) {
    throw "WRITE_SECURE_SETTINGS grant failed."
}

# Turn it on now as well. The boot receiver repeats the same setting after reboot.
adb -s $Phone shell settings put global adb_wifi_enabled 1
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "[4/4] Verification" -ForegroundColor Cyan
$wifiSetting = (adb -s $Phone shell settings get global adb_wifi_enabled).Trim()
Write-Host ("adb_wifi_enabled: " + $wifiSetting)

$grant = adb -s $Phone shell dumpsys package $Package |
    Select-String -Pattern "android.permission.WRITE_SECURE_SETTINGS: granted=true" |
    Select-Object -First 1

if ($grant) {
    Write-Host "WRITE_SECURE_SETTINGS: GRANTED" -ForegroundColor Green
} else {
    Write-Host "WRITE_SECURE_SETTINGS: NOT CONFIRMED" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Wireless ADB mDNS:"
adb mdns services

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " PERSISTENT WIRELESS DEBUGGING SETUP COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Tailscale settings : unchanged"
Write-Host "ADB pairing keys   : unchanged"
Write-Host "USB debugging      : unchanged"
Write-Host "App data           : preserved"
Write-Host "Reboot behavior    : Samsung Secure restores adb_wifi_enabled=1"
Write-Host ""
Write-Host "Next: perform one real reboot and verify without opening Wireless Debugging manually."
