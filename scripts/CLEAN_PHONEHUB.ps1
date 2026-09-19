param(
  [switch]$DeleteArchives
)

$ErrorActionPreference = "Stop"
$Root = "C:\PhoneHub"
$Archive = Join-Path $Root ("archive\cleanup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $Archive | Out-Null

$experimental = @(
  "PhoneHub_USB_V1",
  "PhoneHub_USB_UI_V2",
  "PhoneHub_USB_UI_V3",
  "PhoneHub_USB_UI_V4",
  "PhoneHub_Link_V1",
  "PhoneHub_WireGuard_OneClick",
  "vpn"
)

Write-Host ""
Write-Host "PHONEHUB CLEANUP"
Write-Host "Keeping: Tailscale, ADB/scrcpy runtime, screen control, front/back camera, app backend, file protection, build tools."
Write-Host ""

foreach ($name in $experimental) {
  $p = Join-Path $Root $name
  if (Test-Path $p) {
    $dest = Join-Path $Archive $name
    Move-Item -Path $p -Destination $dest -Force
    Write-Host "[ARCHIVED] $name"
  }
}

# Remove generated secrets/configs accidentally left outside archive candidates.
Get-ChildItem $Root -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object {
    $_.Name -match "PhoneHub-(PC|Phone)\.conf$" -or
    $_.Name -match "wireguard.*\.conf$"
  } |
  ForEach-Object {
    $rel = $_.FullName.Substring($Root.Length).TrimStart("\")
    $safe = $rel -replace '[\\/:*?"<>|]','_'
    Move-Item $_.FullName (Join-Path $Archive $safe) -Force
    Write-Host "[ARCHIVED SECRET] $rel"
  }

Write-Host ""
Write-Host "Current core folders/files preserved:"
$keep = @("app","runtime","scripts","assets","data","docs","tests","companion","PhoneHub.bat","PhoneHub.spec",".git",".github")
foreach ($k in $keep) {
  if (Test-Path (Join-Path $Root $k)) { Write-Host "  KEEP $k" }
}

Write-Host ""
Write-Host "Archive: $Archive"
Write-Host "Cleanup complete."
