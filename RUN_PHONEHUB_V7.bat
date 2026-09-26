@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

where python >nul 2>&1 || (
  echo [PhoneHub] Python 3 is required.
  pause
  exit /b 1
)

where scrcpy >nul 2>&1
if errorlevel 1 (
  echo [PhoneHub 7] Installing high-performance local screen engine...
  where winget >nul 2>&1 || (
    echo [PhoneHub] scrcpy is missing and WinGet is unavailable.
    pause
    exit /b 1
  )
  winget install --exact --id Genymobile.scrcpy --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo [PhoneHub] Could not install scrcpy.
    pause
    exit /b 1
  )
)

python -c "import aiortc, numpy" >nul 2>&1
if errorlevel 1 (
  echo [PhoneHub 7] Installing one-time live-screen components...
  python -m pip install --disable-pip-version-check "aiortc==1.15.0" "numpy>=2,<3"
  if errorlevel 1 (
    echo [PhoneHub] Could not install WebRTC components.
    pause
    exit /b 1
  )
)

echo [PhoneHub 7] Starting Companion + hybrid scrcpy/WebRTC controller...
python -m phonehub_v7.desktop
exit /b %errorlevel%
