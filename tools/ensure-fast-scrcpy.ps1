$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $PSScriptRoot "runtime"
$targetRoot = Join-Path $runtimeRoot "scrcpy-v3.3.4"
$targetExe = Join-Path $targetRoot "scrcpy-win64-v3.3.4\scrcpy.exe"
$zipPath = Join-Path $runtimeRoot "scrcpy-win64-v3.3.4.zip"

$expectedSha256 = "d8a155b7c180b7ca4cdadd40712b8750b63f3aab48cb5b8a2a39ac2d0d4c5d38"
$url = "https://github.com/Genymobile/scrcpy/releases/download/v3.3.4/scrcpy-win64-v3.3.4.zip"

if (Test-Path $targetExe) {
    Write-Output $targetExe
    exit 0
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

if (-not (Test-Path $zipPath)) {
    Write-Host "[AndroidBridge] Installing compact scrcpy media engine (one time)..."
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
}

$actual = (Get-FileHash -Algorithm SHA256 -Path $zipPath).Hash.ToLowerInvariant()
if ($actual -ne $expectedSha256) {
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    throw "scrcpy v3.3.4 checksum mismatch. Fast engine was not installed."
}

Remove-Item $targetRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
Expand-Archive -Path $zipPath -DestinationPath $targetRoot -Force

if (-not (Test-Path $targetExe)) {
    throw "scrcpy v3.3.4 extraction did not produce scrcpy.exe"
}

Write-Output $targetExe
