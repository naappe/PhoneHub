param(
  [string]$Root = "C:\PhoneHub"
)

$ErrorActionPreference = "Stop"
$Runtime = Join-Path $Root "runtime\scrcpy"
$Tmp = Join-Path $env:TEMP ("phonehub_scrcpy_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

try {
  Write-Host "[PhoneHub] Finding latest official scrcpy Windows release..."
  $headers = @{ "User-Agent" = "PhoneHub-Setup" }
  $release = Invoke-RestMethod -UseBasicParsing -Headers $headers -Uri "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"

  $asset = $release.assets | Where-Object { $_.name -match "scrcpy-win64.*\.zip$" } | Select-Object -First 1
  if (-not $asset) {
    throw "Official scrcpy win64 ZIP was not found in the latest release."
  }

  $zip = Join-Path $Tmp $asset.name
  Write-Host "[PhoneHub] Downloading $($asset.name)..."
  Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $asset.browser_download_url -OutFile $zip

  Unblock-File -Path $zip -ErrorAction SilentlyContinue
  $extract = Join-Path $Tmp "extract"
  Expand-Archive -Path $zip -DestinationPath $extract -Force

  $scrcpy = Get-ChildItem $extract -Recurse -File -Filter "scrcpy.exe" | Select-Object -First 1
  if (-not $scrcpy) { throw "scrcpy.exe was not found after extraction." }

  $src = $scrcpy.Directory.FullName
  if (Test-Path $Runtime) {
    Remove-Item $Runtime -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
  Copy-Item (Join-Path $src "*") $Runtime -Recurse -Force

  Get-ChildItem $Runtime -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

  if (-not (Test-Path (Join-Path $Runtime "scrcpy.exe"))) {
    throw "scrcpy installation did not complete."
  }
  if (-not (Test-Path (Join-Path $Runtime "adb.exe"))) {
    throw "adb.exe is missing from the scrcpy runtime."
  }

  Write-Host "[OK] scrcpy runtime installed to $Runtime"
}
finally {
  Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
