$Host.UI.RawUI.WindowTitle = "PhoneHub Launcher"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "         PHONEHUB LAUNCHER"
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# ---------- Read Config ----------
$configPath = "$HOME\.phone_remote\config.json"

if (!(Test-Path $configPath)) {
    Write-Host "[ERROR] Config not found!" -ForegroundColor Red
    Read-Host
    exit
}

$config = Get-Content $configPath | ConvertFrom-Json

$Target = "$($config.phone_ip):$($config.adb_port)"

Write-Host "Phone : $($config.device_name)"
Write-Host "Target: $Target"
Write-Host ""

# ---------- Check Programs ----------
foreach($cmd in @("python","adb","scrcpy","tailscale")){
    if(Get-Command $cmd -ErrorAction SilentlyContinue){
        Write-Host "[OK] $cmd"
    }else{
        Write-Host "[ERROR] $cmd not found" -ForegroundColor Red
        Read-Host
        exit
    }
}

Write-Host ""

# ---------- Check ADB ----------
$devices = adb devices

if($devices -match [regex]::Escape($Target)){
    Write-Host "[OK] Phone already connected." -ForegroundColor Green
}
else{
    Write-Host "Connecting to phone..."
    adb connect $Target | Out-Host
}

Write-Host ""

# ---------- Launch GUI ----------
Write-Host "Starting PhoneHub..." -ForegroundColor Green

Start-Process python "C:\PhoneHub\PhoneHub.py"
