@echo off
setlocal
cd /d "%~dp0"
echo.
echo Installing AndroidBridge desktop icon...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\INSTALL-DESKTOP-ICON.ps1"
if errorlevel 1 (
    echo.
    echo AndroidBridge desktop icon setup FAILED.
    pause
    exit /b 1
)
echo.
echo Done. You can now open AndroidBridge from the desktop icon.
pause
