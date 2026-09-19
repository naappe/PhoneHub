@echo off
setlocal EnableExtensions EnableDelayedExpansion
title PhoneHub One-Run Diagnostic
cd /d C:\PhoneHub

set "OUT=C:\PhoneHub\logs\diagnostic"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%" >nul 2>&1

echo PhoneHub diagnostic started > "%OUT%\summary.txt"
echo Date: %date% %time%>> "%OUT%\summary.txt"
echo.>> "%OUT%\summary.txt"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$p=Join-Path $env:USERPROFILE '.phone_remote\config.json'; if(Test-Path $p){$j=Get-Content $p -Raw ^| ConvertFrom-Json; if($j.phone_ip){$port=5555; if($j.adb_port){$port=[int]$j.adb_port}; Write-Output ($j.phone_ip.ToString()+':'+$port.ToString())}}"`) do set "TARGET=%%I"

if not defined TARGET (
  echo ERROR: Phone target not found in config.>> "%OUT%\summary.txt"
  goto collect_static
)

echo Target: %TARGET%>> "%OUT%\summary.txt"

adb start-server >nul 2>&1
adb devices -l > "%OUT%\adb_devices_before.txt" 2>&1
adb -s %TARGET% shell echo PHONEHUB_OK > "%OUT%\adb_probe_before.txt" 2>&1
adb -s %TARGET% shell getprop ro.product.model > "%OUT%\model.txt" 2>&1
adb -s %TARGET% shell getprop ro.build.version.release > "%OUT%\android_version.txt" 2>&1
adb -s %TARGET% shell getprop sys.usb.config > "%OUT%\usb_config.txt" 2>&1
adb -s %TARGET% shell getprop service.adb.tcp.port > "%OUT%\adb_tcp_port.txt" 2>&1
adb -s %TARGET% shell settings get global adb_enabled > "%OUT%\adb_enabled.txt" 2>&1
adb -s %TARGET% shell dumpsys power > "%OUT%\power_before.txt" 2>&1
adb -s %TARGET% shell dumpsys window policy > "%OUT%\window_policy_before.txt" 2>&1

echo.
echo ============================================================
echo PHONEHUB DIAGNOSTIC READY
echo ============================================================
echo.
echo 1. Leave this window OPEN.
echo 2. Open PhoneHub Screen.
echo 3. Lock the phone.
echo 4. Wake it and enter the PIN/fingerprint until the screen drops.
echo 5. Come back here and press any key.
echo.
pause >nul

adb devices -l > "%OUT%\adb_devices_after.txt" 2>&1
adb -s %TARGET% shell echo PHONEHUB_OK > "%OUT%\adb_probe_after.txt" 2>&1
adb -s %TARGET% shell dumpsys power > "%OUT%\power_after.txt" 2>&1
adb -s %TARGET% shell dumpsys window policy > "%OUT%\window_policy_after.txt" 2>&1
adb -s %TARGET% logcat -d -t 500 > "%OUT%\android_logcat_after.txt" 2>&1

:collect_static
if exist "C:\PhoneHub\logs\scrcpy_screen.log" copy /y "C:\PhoneHub\logs\scrcpy_screen.log" "%OUT%\scrcpy_screen.log" >nul
if exist "C:\PhoneHub\logs\scrcpy_camera.log" copy /y "C:\PhoneHub\logs\scrcpy_camera.log" "%OUT%\scrcpy_camera.log" >nul
if exist "C:\PhoneHub\logs\launcher_error.log" copy /y "C:\PhoneHub\logs\launcher_error.log" "%OUT%\launcher_error.log" >nul
if exist "C:\PhoneHub\logs\phonehub_stdout.log" copy /y "C:\PhoneHub\logs\phonehub_stdout.log" "%OUT%\phonehub_stdout.log" >nul

tailscale status > "%OUT%\tailscale_status.txt" 2>&1
if defined TARGET (
  for /f "tokens=1 delims=:" %%A in ("%TARGET%") do tailscale ping %%A > "%OUT%\tailscale_ping.txt" 2>&1
)

powershell -NoProfile -Command "Compress-Archive -Path '%OUT%\*' -DestinationPath 'C:\PhoneHub\logs\PhoneHub_Diagnostic.zip' -Force" >nul 2>&1

echo.
echo DONE.
echo Send this one file:
echo C:\PhoneHub\logs\PhoneHub_Diagnostic.zip
echo.
pause
endlocal
