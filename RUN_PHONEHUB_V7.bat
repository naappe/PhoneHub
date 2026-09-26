@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

where python >nul 2>&1 || (
  echo [PhoneHub] Python 3 is required.
  pause
  exit /b 1
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

echo [PhoneHub 7] Starting Companion + WebRTC receiver...
python -m phonehub_v7.desktop
exit /b %errorlevel%
