$ErrorActionPreference = "Stop"

$ConfigDir = "C:\Program Files\EqualizerAPO\config"
$MainConfig = Join-Path $ConfigDir "config.txt"
$BoostConfig = Join-Path $ConfigDir "androidbridge-boost.txt"
$IncludeLine = "Include: androidbridge-boost.txt"

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host "Requesting Administrator permission for one-time AndroidBridge audio boost setup..."
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $PSCommandPath + '"')
    )
    exit
}

Write-Host ""
Write-Host "=============================================="
Write-Host " AndroidBridge PC Audio Boost - One-Time Setup"
Write-Host "=============================================="
Write-Host ""

if (-not (Test-Path $ConfigDir)) {
    Write-Host "Equalizer APO is not installed in the expected location:"
    Write-Host $ConfigDir
    Write-Host ""
    Write-Host "Install Equalizer APO first, select the Windows speaker/headphone output device in its Configurator, then run this setup again."
    Read-Host "Press Enter to close"
    exit 1
}

if (-not (Test-Path $MainConfig)) {
    New-Item -ItemType File -Path $MainConfig -Force | Out-Null
}

$mainText = Get-Content $MainConfig -Raw -ErrorAction SilentlyContinue
if ($null -eq $mainText) { $mainText = "" }

if ($mainText -notmatch '(?im)^\s*Include:\s*androidbridge-boost\.txt\s*$') {
    Add-Content -Path $MainConfig -Value "`r`n# AndroidBridge automatic PC audio boost`r`n$IncludeLine`r`n"
    Write-Host "[OK] Added AndroidBridge boost include to Equalizer APO config."
} else {
    Write-Host "[OK] AndroidBridge boost include already exists."
}

Set-Content -Path $BoostConfig -Value "Preamp: +0.00 dB" -Encoding ASCII

# Permit the signed-in user to update only the dedicated AndroidBridge boost file.
$Account = "$env:USERDOMAIN\$env:USERNAME"
& icacls.exe $BoostConfig /grant "${Account}:(M)" | Out-Null

Write-Host "[OK] Created: $BoostConfig"
Write-Host "[OK] AndroidBridge can now change PC gain without reconnecting the phone."
Write-Host ""

$Configurator = "C:\Program Files\EqualizerAPO\Configurator.exe"
if (Test-Path $Configurator) {
    Write-Host "IMPORTANT: Equalizer APO must be enabled for the speaker/headphone device used by AndroidBridge."
    Write-Host "Opening Configurator so you can verify the correct output device is selected."
    Start-Process $Configurator
}

Write-Host ""
Write-Host "After device selection, Windows may request a restart."
Write-Host "Then replace C:\AndroidBridge-Lite\AndroidBridge-Lite.py with AndroidBridge-Lite-AutoBoost.py."
Write-Host ""
Read-Host "Press Enter to close"