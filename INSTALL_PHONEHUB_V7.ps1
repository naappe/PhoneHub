param()
$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Apk=Join-Path $Root "dist\PhoneHub-Companion-7.0.0-dev3.apk"
$Pkg="com.phonehub.companion"
if(-not(Test-Path $Apk)){throw "APK not found: $Apk"}
if(-not(Get-Command adb -ErrorAction SilentlyContinue)){throw "adb not found."}
$dev=& adb devices
if(-not($dev -match "\sdevice\s*$")){throw "No authorized Android device connected."}
Write-Host "[1/3] Installing PhoneHub Companion..."
$out=(& adb install -r $Apk 2>&1 | Out-String)
if($out -match "INSTALL_FAILED_UPDATE_INCOMPATIBLE"){
  Write-Host ""
  Write-Host "One-time signing migration required."
  Write-Host "The installed dev build has a different temporary signature."
  $answer=Read-Host "Replace the old Companion now? This clears its app data. [Y/N]"
  if($answer -notmatch '^[Yy]'){throw "Installation cancelled."}
  & adb uninstall $Pkg
  if($LASTEXITCODE -ne 0){throw "Could not remove old Companion."}
  $out=(& adb install $Apk 2>&1 | Out-String)
}
Write-Host $out.Trim()
if($out -notmatch "Success"){throw "APK installation failed."}
Write-Host "[2/3] Launching Companion..."
& adb shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null
Write-Host "[3/3] Installed and launched."
Write-Host ""
Write-Host "If this was the one-time signing migration, tap Enable automatic service once on the phone."
