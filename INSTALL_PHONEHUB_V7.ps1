param()
$ErrorActionPreference="Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Apk=Join-Path $Root "dist\PhoneHub-Companion-7.0.0-dev17.apk"
$Pkg="com.phonehub.companion"
if(-not(Test-Path $Apk)){throw "APK not found: $Apk"}
if(-not(Get-Command adb -ErrorAction SilentlyContinue)){throw "adb not found."}

$devices = @(& adb devices | Select-Object -Skip 1 | ForEach-Object {
    if ($_ -match '^([^\s]+)\s+device\s*$') { $matches[1] }
})
if($devices.Count -eq 0){throw "No authorized Android device connected."}

# Prefer a directly attached USB device for installation. Otherwise use the sole device.
$serial = $null
$usb = @($devices | Where-Object { $_ -notmatch ':\d+$' })
if($usb.Count -eq 1){ $serial = $usb[0] }
elseif($devices.Count -eq 1){ $serial = $devices[0] }
else {
    Write-Host "Multiple Android devices are connected:"
    for($i=0;$i -lt $devices.Count;$i++){ Write-Host " [$($i+1)] $($devices[$i])" }
    $choice=[int](Read-Host "Select the phone number")
    if($choice -lt 1 -or $choice -gt $devices.Count){throw "Invalid device selection."}
    $serial=$devices[$choice-1]
}
Write-Host "Using device: $serial"

Write-Host "[1/3] Installing PhoneHub Companion..."
$out = cmd /c "adb -s $serial install -r `"$Apk`" 2>&1" | Out-String
if($out -match "INSTALL_FAILED_UPDATE_INCOMPATIBLE"){
  Write-Host ""
  Write-Host "One-time signing migration required."
  Write-Host "The installed dev build has a different temporary signature."
  $answer=Read-Host "Replace the old Companion now? This clears its app data. [Y/N]"
  if($answer -notmatch '^[Yy]'){throw "Installation cancelled."}
  & adb -s $serial uninstall $Pkg
  if($LASTEXITCODE -ne 0){throw "Could not remove old Companion."}
  $out = cmd /c "adb -s $serial install `"$Apk`" 2>&1" | Out-String
}
Write-Host $out.Trim()
if($out -notmatch "Success"){throw "APK installation failed."}
Write-Host "[2/3] Launching Companion..."
& adb -s $serial shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null
Write-Host "[3/4] Installed and launched."
Write-Host "[4/4] Enabling authorized wireless ADB for local high-performance screen..."

function Test-PhoneHubTcpPort([string]$HostName,[int]$Port,[int]$TimeoutMs=1200) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName,$Port,$null,$null)
        if(-not $async.AsyncWaitHandle.WaitOne($TimeoutMs,$false)){ return $false }
        $client.EndConnect($async)
        return $client.Connected
    } catch { return $false }
    finally { $client.Close() }
}

$candidates = New-Object System.Collections.Generic.List[string]
function Add-PhoneHubCandidate([string]$Ip) {
    if($Ip -match '^\d{1,3}(\.\d{1,3}){3}$' -and -not $candidates.Contains($Ip)) { $candidates.Add($Ip) }
}

# Ask Android which source address it would use to reach each active PC IPv4.
# This avoids accidentally choosing cellular/VPN addresses from a generic route dump.
try {
    $pcIps = @(Get-NetIPConfiguration -ErrorAction Stop |
        Where-Object { $_.NetAdapter.Status -eq "Up" } |
        ForEach-Object { $_.IPv4Address.IPAddress } |
        Where-Object { $_ -and $_ -notmatch '^(127\.|169\.254\.)' })
    foreach($pcIp in $pcIps) {
        $route = (& adb -s $serial shell ip -4 route get $pcIp 2>$null | Out-String)
        if($route -match '\bsrc\s+(\d+\.\d+\.\d+\.\d+)') { Add-PhoneHubCandidate $matches[1] }
    }
} catch {}

# Wi-Fi-specific fallback for Android builds where route-get is restricted.
$wifiAddr = (& adb -s $serial shell ip -4 addr show wlan0 2>$null | Out-String)
if($wifiAddr -match '\binet\s+(\d+\.\d+\.\d+\.\d+)/\d+') { Add-PhoneHubCandidate $matches[1] }
$wifiRoute = (& adb -s $serial shell ip -4 route show dev wlan0 2>$null | Out-String)
if($wifiRoute -match '\bsrc\s+(\d+\.\d+\.\d+\.\d+)') { Add-PhoneHubCandidate $matches[1] }

$tcp = (& adb -s $serial tcpip 5555 2>&1 | Out-String).Trim()
if($LASTEXITCODE -eq 0){
    Write-Host "Wireless ADB enabled on TCP 5555."
    Start-Sleep -Seconds 2
    $connectedTarget = $null
    foreach($phoneIp in $candidates) {
        $target = "${phoneIp}:5555"
        Write-Host "Testing local target: $target"
        if(-not (Test-PhoneHubTcpPort $phoneIp 5555 1200)) {
            Write-Host "  Not reachable from this PC."
            continue
        }
        $connect = (& adb connect $target 2>&1 | Out-String).Trim()
        Write-Host "  $connect"
        if($connect -match '(?i)(connected to|already connected)') {
            $connectedTarget = $target
            break
        }
    }
    if($connectedTarget) {
        $stateDir = Join-Path $HOME ".phonehub"
        New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
        Set-Content -Path (Join-Path $stateDir "wireless_adb_target.txt") -Value $connectedTarget -Encoding ASCII
        Write-Host "Local high-performance target saved: $connectedTarget"
    } else {
        Write-Host "No PC-reachable Wi-Fi ADB address was found."
        Write-Host "PhoneHub will automatically use encrypted Companion/WebRTC fallback instead."
    }
} else {
    Write-Host "Wireless ADB setup skipped: $tcp"
}
Write-Host ""
Write-Host "PhoneHub Companion upgrade complete."
