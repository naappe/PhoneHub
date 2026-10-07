param(
    [string]$ProjectRoot = "C:\Project-Archive\AndroidBridge-Calls"
)

$ErrorActionPreference = "Stop"
$Package = "com.androidbridge.calls"

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Replace-Literal([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if ($Text.Contains($Old)) {
        Write-Host ("  CHANGE: " + $Label) -ForegroundColor Green
        return $Text.Replace($Old, $New)
    }
    if ($Text.Contains($New)) {
        Write-Host ("  ALREADY: " + $Label) -ForegroundColor DarkGray
        return $Text
    }
    Write-Host ("  SKIP: " + $Label + " (exact old text not present)") -ForegroundColor Yellow
    return $Text
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " SAMSUNG SECURE - MOBILE CHINESE PATCH" -ForegroundColor Cyan
Write-Host " Mobile project only. PC AndroidBridge is not modified." -ForegroundColor DarkGray
Write-Host " Package/protocol/service identities remain unchanged." -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $ProjectRoot)) {
    throw "Mobile project not found: $ProjectRoot"
}

$Main = Join-Path $ProjectRoot "app\src\main\java\com\androidbridge\MainActivity.java"
$Manifest = Join-Path $ProjectRoot "app\src\main\AndroidManifest.xml"
$Bridge = Join-Path $ProjectRoot "app\src\main\java\com\androidbridge\BridgeService.java"
$Gps = Join-Path $ProjectRoot "app\src\main\java\com\androidbridge\OfflineLocationService.java"
$Camera = Join-Path $ProjectRoot "app\src\main\java\com\androidbridge\CameraService.java"
$Screen = Join-Path $ProjectRoot "app\src\main\java\com\androidbridge\ScreenService.java"

foreach ($f in @($Main,$Manifest,$Bridge,$Gps,$Camera,$Screen)) {
    if (-not (Test-Path $f)) { throw "Required source file missing: $f" }
}

$Backup = Join-Path $env:TEMP ("SamsungSecure-Mobile-Backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $Backup -Force | Out-Null
foreach ($f in @($Main,$Manifest,$Bridge,$Gps,$Camera,$Screen)) {
    Copy-Item $f (Join-Path $Backup ([IO.Path]::GetFileName($f))) -Force
}
Write-Host ("Safety copy: " + $Backup) -ForegroundColor DarkGray

Write-Host ""
Write-Host "[1/5] App name / Android labels" -ForegroundColor Cyan
$x = [IO.File]::ReadAllText($Manifest)
$x = Replace-Literal $x 'android:label="AndroidBridge Calls"' 'android:label="Samsung Secure"' "AndroidBridge Calls -> Samsung Secure"
$x = Replace-Literal $x 'android:label="AndroidBridge"' 'android:label="Samsung Secure"' "AndroidBridge -> Samsung Secure label"
Write-Utf8NoBom $Manifest $x

Write-Host ""
Write-Host "[2/5] Circled Calls screen -> Simplified Chinese" -ForegroundColor Cyan
$x = [IO.File]::ReadAllText($Main)
$ui = @(
    @('"AndroidBridge Calls"', '"Samsung Secure"', "screen title"),
    @('"Call history companion"', '"通话记录助手"', "subtitle"),
    @('"CALL LOG ACCESS: ALLOWED"', '"通话记录权限：已允许"', "permission allowed"),
    @('"CALL LOG ACCESS: REQUIRED"', '"通话记录权限：需要授权"', "permission required"),
    @('"CALL LOG ACCESS: DENIED"', '"通话记录权限：已拒绝"', "permission denied"),
    @('"ALLOW CALL ACCESS"', '"允许通话记录访问"', "allow button"),
    @('"REFRESH CALLS"', '"刷新通话记录"', "refresh button"),
    @('"LAST OUTGOING"', '"最近拨出"', "last outgoing"),
    @('"No outgoing calls"', '"无拨出通话"', "no outgoing"),
    @('"MISSED CALLS"', '"未接来电"', "missed calls"),
    @('"No missed calls"', '"无未接来电"', "no missed calls"),
    @('"RECENT CALLS"', '"最近通话"', "recent calls"),
    @('"No recent calls"', '"无最近通话"', "no recent calls")
)
foreach ($r in $ui) { $x = Replace-Literal $x $r[0] $r[1] $r[2] }
Write-Utf8NoBom $Main $x

Write-Host ""
Write-Host "[3/5] Visible Android notifications -> Samsung Secure / Chinese" -ForegroundColor Cyan
$x = [IO.File]::ReadAllText($Bridge)
$bridgeUi = @(
    @('"AndroidBridge Connection"', '"Samsung Secure 连接"', "connection notification channel"),
    @('.setContentTitle("AndroidBridge")', '.setContentTitle("Samsung Secure")', "bridge notification title"),
    @('.setContentText("Bridge running")', '.setContentText("安全服务正在运行")', "bridge notification text"),
    @('"AndroidBridge",', '"Samsung Secure",', "visible bridge alert title"),
    @('"SCREEN START FAILED"', '"屏幕启动失败"', "screen start alert"),
    @('"SCREEN PAUSE FAILED"', '"屏幕暂停失败"', "screen pause alert")
)
foreach ($r in $bridgeUi) { $x = Replace-Literal $x $r[0] $r[1] $r[2] }
Write-Utf8NoBom $Bridge $x

$x = [IO.File]::ReadAllText($Gps)
$gpsUi = @(
    @('"Offline GPS logging active"', '"离线定位记录已启用"', "GPS foreground text"),
    @('"AndroidBridge Offline GPS"', '"Samsung Secure 离线定位"', "GPS channel"),
    @('"Stores GPS fixes locally while the phone is offline."', '"手机离线时在本机保存 GPS 位置记录。"', "GPS channel description"),
    @('setContentTitle("AndroidBridge")', 'setContentTitle("Samsung Secure")', "GPS notification title"),
    @('"GPS history synced to AndroidBridge PC"', '"GPS 位置记录已同步"', "GPS synced"),
    @('"Offline - GPS fixes saved on phone"', '"离线状态 - GPS 位置已保存在手机中"', "GPS offline")
)
foreach ($r in $gpsUi) { $x = Replace-Literal $x $r[0] $r[1] $r[2] }
Write-Utf8NoBom $Gps $x

foreach ($f in @($Camera,$Screen)) {
    $x = [IO.File]::ReadAllText($f)
    $x = Replace-Literal $x '"AndroidBridge"' '"Samsung Secure"' ([IO.Path]::GetFileName($f) + " visible title")
    Write-Utf8NoBom $f $x
}

Write-Host ""
Write-Host "[4/5] Safety verification" -ForegroundColor Cyan
$all = ((Get-Content $Bridge,$Main,$Gps,$Camera,$Screen -Raw) -join [Environment]::NewLine)
$projectText = (Get-ChildItem $ProjectRoot -Recurse -File -Include *.java,*.xml,*.gradle |
    ForEach-Object { Get-Content $_.FullName -Raw }) -join [Environment]::NewLine

if ($all -notmatch 'ANDROIDBRIDGE') { throw "STOP: ANDROIDBRIDGE protocol marker is missing." }
if ($all -notmatch 'STATUS=ONLINE') { throw "STOP: STATUS=ONLINE protocol marker is missing." }
if ($all -notmatch 'COMMAND_OK=') { throw "STOP: COMMAND_OK protocol marker is missing." }
if ($projectText -notmatch [regex]::Escape($Package)) { throw "STOP: package identity $Package is missing." }

Write-Host "Protocol markers: KEPT" -ForegroundColor Green
Write-Host "Package identity : KEPT ($Package)" -ForegroundColor Green
Write-Host "PC controller    : NOT TOUCHED" -ForegroundColor Green

Write-Host ""
Write-Host "[5/5] Build debug APK" -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & .\gradlew.bat clean assembleDebug
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$Apk = Join-Path $ProjectRoot "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $Apk)) { throw "Build completed but APK was not found: $Apk" }

Write-Host ""
Write-Host "APK READY" -ForegroundColor Green
Write-Host $Apk

$rows = @(adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\sdevice\s*$" })
$serials = @($rows | ForEach-Object { ($_ -split "\s+")[0] })
$Device = $null
$preferredUsb = @($serials | Where-Object { $_ -eq "R5CY20RCX8E" })

if ($preferredUsb.Count -gt 0) {
    $Device = $preferredUsb[0]
} elseif ($serials.Count -gt 0) {
    $Device = $serials[0]
}

if (-not $Device) {
    Write-Host ""
    Write-Host "No online ADB device listed. Trying mDNS discovery without re-pairing..." -ForegroundColor Yellow
    $mdns = @(adb mdns services)
    $service = $mdns | Where-Object {
        $_ -match "R5CY20RCX8E" -and $_ -match "_adb-tls-connect\._tcp"
    } | Select-Object -First 1

    if ($service -and $service -match '(\d{1,3}(?:\.\d{1,3}){3}:\d+)') {
        $Device = $Matches[1]
        adb connect $Device | Out-Host
        Start-Sleep -Seconds 2
    }
}

if (-not $Device -or -not ((adb devices | Out-String) -match ([regex]::Escape($Device) + "\s+device"))) {
    Write-Host ""
    Write-Host "APK built successfully, but no online authorized ADB device is available for installation." -ForegroundColor Yellow
    Write-Host "No pairing/reset/uninstall was attempted."
    exit 0
}

Write-Host ""
Write-Host ("Installing in place on: " + $Device) -ForegroundColor Cyan
adb -s $Device install -r $Apk
if ($LASTEXITCODE -ne 0) {
    throw "APK update failed. The existing app was NOT uninstalled."
}

adb -s $Device shell am start -n com.androidbridge.calls/.MainActivity | Out-Null
Start-Sleep -Seconds 1
adb -s $Device shell am start -n com.androidbridge.calls/com.androidbridge.OfflineLocationSetupActivity --ez enable_offline_gps true | Out-Null
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " SAMSUNG SECURE MOBILE UPDATE COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Phone app name  : Samsung Secure"
Write-Host "Phone UI        : Simplified Chinese"
Write-Host "Package         : com.androidbridge.calls (unchanged)"
Write-Host "Protocol        : unchanged"
Write-Host "PC AndroidBridge: unchanged"
Write-Host ""
Write-Host "Running services:"
adb -s $Device shell dumpsys activity services $Package |
    Select-String -Pattern "BridgeService|OfflineLocationService" -CaseSensitive:$false
Write-Host ""
Write-Host "Doze whitelist:"
adb -s $Device shell cmd deviceidle whitelist |
    Select-String -Pattern "androidbridge" -CaseSensitive:$false
