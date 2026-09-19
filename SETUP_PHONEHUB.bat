@echo off
setlocal
title PhoneHub Setup
cd /d C:\PhoneHub

echo ==========================================
echo  PHONEHUB - TAILSCALE SETUP
echo ==========================================
echo.

set "TAILSCALE_EXE="
where tailscale >nul 2>&1
if not errorlevel 1 set "TAILSCALE_EXE=tailscale"
if not defined TAILSCALE_EXE if exist "C:\Program Files\Tailscale\tailscale.exe" set "TAILSCALE_EXE=C:\Program Files\Tailscale\tailscale.exe"

if not defined TAILSCALE_EXE (
  echo [ERROR] Tailscale was not found.
  echo Install/open Tailscale, sign in, then run this setup again.
  pause
  exit /b 1
)

if not exist "C:\PhoneHub\runtime\scrcpy\scrcpy.exe" (
  echo [PhoneHub] scrcpy runtime is missing.
  echo [PhoneHub] Installing the official scrcpy Windows runtime automatically...
  powershell -NoProfile -ExecutionPolicy Bypass -File "C:\PhoneHub\scripts\INSTALL_SCRCPY_RUNTIME.ps1"
  if errorlevel 1 (
    echo [ERROR] Automatic scrcpy installation failed.
    pause
    exit /b 1
  )
)

set "PATH=C:\PhoneHub\runtime\scrcpy;%PATH%"

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python was not found.
  pause
  exit /b 1
)

echo [PhoneHub] Checking Python dependencies...
python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo [PhoneHub] Installing required Python UI package...
  python -m pip install --disable-pip-version-check -r "C:\PhoneHub\requirements.txt"
  if errorlevel 1 (
    echo [ERROR] Python dependency installation failed.
    pause
    exit /b 1
  )
)

where adb >nul 2>&1
if errorlevel 1 (
  echo [ERROR] ADB runtime not found after setup.
  pause
  exit /b 1
)

if not exist "C:\PhoneHub\runtime\scrcpy\scrcpy.exe" (
  echo [ERROR] scrcpy runtime is still missing.
  pause
  exit /b 1
)

echo [OK] Tailscale found.
echo [OK] Python found.
echo [OK] PySide6 found.
echo [OK] ADB found.
echo [OK] scrcpy found.
echo.

echo Starting ADB...
adb start-server >nul 2>&1

echo.
echo Tailscale addresses:
"%TAILSCALE_EXE%" ip -4 2>nul

echo.
echo PhoneHub is ready.
echo USB is only needed for initial Android debugging authorization or repair.
echo Daily use: Tailscale ON on PC + phone, then run C:\PhoneHub\PhoneHub.bat.
echo.
pause
endlocal
