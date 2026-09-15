$Host.UI.RawUI.WindowTitle = "PhoneHub EXE Builder"

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "       PHONEHUB EXE BUILD"
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

cd C:\PhoneHub

Write-Host "Installing/checking PyInstaller..."
python -m pip install pyinstaller

Write-Host ""
Write-Host "Building PhoneHub.exe..."
python -m PyInstaller --onefile --windowed --name PhoneHub --paths "C:\PhoneHub\app" "C:\PhoneHub\app\PhoneHub.py"

Write-Host ""
Write-Host "Done."
Write-Host "EXE location:"
Write-Host "C:\PhoneHub\dist\PhoneHub.exe" -ForegroundColor Green
