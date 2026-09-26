@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

where python >nul 2>&1 || (
  echo [PhoneHub] Python 3 is required.
  pause
  exit /b 1
)

echo [PhoneHub 7] Starting direct Companion receiver...
python -m phonehub_v7.desktop
exit /b %errorlevel%
