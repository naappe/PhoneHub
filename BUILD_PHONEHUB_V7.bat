@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BUILD_PHONEHUB_V7.ps1"
if errorlevel 1 (
  echo.
  echo PhoneHub V7 build failed.
  pause
  exit /b 1
)
echo.
echo PhoneHub V7 signed APK build complete.
pause
