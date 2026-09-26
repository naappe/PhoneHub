@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_PHONEHUB_V7.ps1"
if errorlevel 1 (
  echo.
  echo PhoneHub V7 installation failed.
  pause
  exit /b 1
)
echo.
echo PhoneHub V7 installation complete.
pause
