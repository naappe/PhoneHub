param()
$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
Write-Host "PhoneHub V7 safe cleanup"
Get-Process python,pythonw,scrcpy -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
try { & (Join-Path $Root "gradlew.bat") --stop *> $null } catch {}
$junk=@(
  (Join-Path $Root ".gradle"),
  (Join-Path $Root "companion\build"),
  (Join-Path $Root "dist"),
  (Join-Path $Root "src\phonehub.egg-info")
)
foreach($p in $junk){if(Test-Path $p){Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue}}
Get-ChildItem $Root -Directory -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object {$_.Name -eq "__pycache__"} |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $Root -File -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object {$_.Name -match '\.(tmp|bak|old|log)$' -or $_.Name -like '*.crdownload'} |
  Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host "Kept current Companion, PC source, phone-baselines, signing key, Gradle wrapper, and current scripts."
git status --short
