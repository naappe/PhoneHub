@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

where python >nul 2>&1 || (
  echo [PhoneHub Setup] Python 3 is required.
  echo Install Python, then run this file again.
  pause
  exit /b 1
)

python -c "import PySide6" >nul 2>&1 || (
  echo [PhoneHub Setup] Installing PhoneHub UI dependency...
  python -m pip install "PySide6>=6.8,<7" || goto :failed
)

where tailscale >nul 2>&1
if errorlevel 1 (
  echo [PhoneHub Setup] Tailscale is missing on this PC.
  where winget >nul 2>&1 || (
    echo [PhoneHub Setup] Windows Package Manager ^(winget^) is required for automatic Tailscale installation.
    echo Install Tailscale manually, then run PhoneHub again.
    pause
    exit /b 1
  )
  echo [PhoneHub Setup] Installing Tailscale automatically...
  winget install --id Tailscale.Tailscale -e --accept-package-agreements --accept-source-agreements || goto :failed
)

echo [PhoneHub Setup] Tailscale available.

rem Install PC-side Android tools once. Normal startup remains automatic.
where adb >nul 2>&1 || (
  echo [PhoneHub Setup] Installing Android platform tools...
  winget install --id Google.PlatformTools -e --accept-package-agreements --accept-source-agreements || goto :failed
)

where scrcpy >nul 2>&1 || (
  echo [PhoneHub Setup] Installing scrcpy...
  winget install --id Genymobile.scrcpy -e --accept-package-agreements --accept-source-agreements || goto :failed
)

echo [PhoneHub] Starting PhoneHub 6.3...
python -m phonehub
exit /b %errorlevel%

:failed
echo.
echo PhoneHub automatic setup failed.
pause
exit /b 1
