param()
$ErrorActionPreference="Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Apk=Join-Path $Root "dist\PhoneHub-Companion-7.0.0-dev16.apk"
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
$route = (& adb -s $serial shell ip route 2>$null | Out-String)
$phoneIp = $null
if($route -match '\bsrc\s+(\d+\.\d+\.\d+\.\d+)'){ $phoneIp=$matches[1] }
$tcp = (& adb -s $serial tcpip 5555 2>&1 | Out-String).Trim()
if($LASTEXITCODE -eq 0){
  Write-Host "Wireless ADB enabled on TCP 5555."
  if($phoneIp){
    Start-Sleep -Seconds 2
    $target = "${phoneIp}:5555"
    $connect = (& adb connect $target 2>&1 | Out-String).Trim()
    Write-Host "Wireless target: $target"
    Write-Host $connect
  } else {
    Write-Host "Phone Wi-Fi IP was not available; Companion will advertise it securely."
  }
} else { Write-Host "Wireless ADB setup skipped: $tcp" }
Write-Host ""
Write-Host "If this was the one-time signing migration, tap Enable automatic service once on the phone."
