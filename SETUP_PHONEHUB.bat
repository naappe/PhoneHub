@echo off
setlocal
title PhoneHub Setup
cd /d C:\PhoneHub

echo ==========================================
echo  PHONEHUB - TAILSCALE SETUP
echo ==========================================
echo.

where tailscale >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Tailscale is not installed or not in PATH.
  echo Install/open Tailscale, sign in, then run this again.
  pause
  exit /b 1
)

where adb >nul 2>&1
if errorlevel 1 (
  if exist "C:\PhoneHub\runtime\scrcpy\adb.exe" (
    set "PATH=C:\PhoneHub\runtime\scrcpy;%PATH%"
  ) else (
    echo [ERROR] ADB runtime not found.
    pause
    exit /b 1
  )
)

if not exist "C:\PhoneHub\runtime\scrcpy\scrcpy.exe" (
  echo [ERROR] scrcpy runtime not found under runtime\scrcpy.
  pause
  exit /b 1
)

echo [OK] Tailscale found.
echo [OK] ADB found.
echo [OK] scrcpy found.
echo.
echo Starting ADB...
adb start-server >nul 2>&1

echo.
echo Tailscale addresses:
tailscale ip -4 2>nul
echo.
echo PhoneHub is ready.
echo USB is only needed for first Android debugging authorization/repair.
echo Daily use: Tailscale ON on PC + phone, then run PhoneHub.bat.
echo.
pause
endlocal
