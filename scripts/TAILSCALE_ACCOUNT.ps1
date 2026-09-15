Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "     PHONEHUB TAILSCALE ACCOUNT"
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Current Tailscale status:" -ForegroundColor Yellow
tailscale status
Write-Host ""

Write-Host "Choose option:" -ForegroundColor Cyan
Write-Host "1. Keep current account"
Write-Host "2. Logout current account"
Write-Host "3. Login / add another account"
Write-Host "4. Logout then login another account"
Write-Host ""

$choice = Read-Host "Type 1, 2, 3, or 4"

if ($choice -eq "1") {
    Write-Host "Keeping current Tailscale account." -ForegroundColor Green
}

elseif ($choice -eq "2") {
    Write-Host "Logging out Tailscale..." -ForegroundColor Yellow
    tailscale logout
    Write-Host "Logged out." -ForegroundColor Green
}

elseif ($choice -eq "3") {
    Write-Host "Opening Tailscale login..." -ForegroundColor Yellow
    tailscale up
    Write-Host ""
    Write-Host "Browser should open. Login with the Gmail you want." -ForegroundColor Cyan
    Write-Host "Use the SAME Tailscale Gmail on PC and phone." -ForegroundColor Cyan
}

elseif ($choice -eq "4") {
    Write-Host "Logging out old Tailscale account..." -ForegroundColor Yellow
    tailscale logout
    Start-Sleep -Seconds 2

    Write-Host "Opening Tailscale login for new account..." -ForegroundColor Yellow
    tailscale up

    Write-Host ""
    Write-Host "Browser should open. Login with the Gmail you want." -ForegroundColor Cyan
    Write-Host "Use the SAME Tailscale Gmail on PC and phone." -ForegroundColor Cyan
}

else {
    Write-Host "Invalid choice." -ForegroundColor Red
}

Write-Host ""
Write-Host "After login, run this to confirm:" -ForegroundColor Yellow
Write-Host "tailscale status"
Write-Host ""
pause
