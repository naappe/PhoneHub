param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$AssetsDir = Join-Path $RepoRoot "assets\icons"
$IconPath = Join-Path $AssetsDir "AndroidBridge.ico"
$VbsPath = Join-Path $RepoRoot "AndroidBridge.vbs"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "AndroidBridge.lnk"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$StartShortcutPath = Join-Path $StartMenuDir "AndroidBridge.lnk"

New-Item -ItemType Directory -Force -Path $AssetsDir | Out-Null

Add-Type -AssemblyName System.Drawing

# Build a real Windows .ico locally. No downloaded icon pack is required.
$size = 256
$bmp = New-Object System.Drawing.Bitmap($size, $size)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.Color]::Transparent)

$bg = [System.Drawing.Color]::FromArgb(255, 8, 25, 55)
$edge = [System.Drawing.Color]::FromArgb(255, 36, 151, 255)
$white = [System.Drawing.Color]::FromArgb(255, 245, 249, 255)
$cyan = [System.Drawing.Color]::FromArgb(255, 83, 205, 255)

$bgBrush = New-Object System.Drawing.SolidBrush($bg)
$edgePen = New-Object System.Drawing.Pen($edge, 10)
$whitePen = New-Object System.Drawing.Pen($white, 15)
$cyanPen = New-Object System.Drawing.Pen($cyan, 13)
$whitePen.StartCap = $whitePen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$cyanPen.StartCap = $cyanPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$edgePen.StartCap = $edgePen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round

# Rounded-square app tile.
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$r = 42
$path.AddArc(12, 12, $r, $r, 180, 90)
$path.AddArc($size-12-$r, 12, $r, $r, 270, 90)
$path.AddArc($size-12-$r, $size-12-$r, $r, $r, 0, 90)
$path.AddArc(12, $size-12-$r, $r, $r, 90, 90)
$path.CloseFigure()
$g.FillPath($bgBrush, $path)
$g.DrawPath($edgePen, $path)

# Phone outline.
$phone = New-Object System.Drawing.Drawing2D.GraphicsPath
$phone.AddLine(82, 55, 82, 201)
$phone.AddArc(82, 45, 28, 28, 180, 90)
$phone.AddLine(96, 45, 145, 45)
$phone.AddLine(145, 45, 145, 77)
$g.DrawPath($whitePen, $phone)
$g.DrawLine($whitePen, 82, 201, 137, 201)
$g.DrawLine($whitePen, 108, 219, 127, 219)

# Wireless bridge arcs.
$g.DrawArc($cyanPen, 112, 82, 92, 76, 205, 130)
$g.DrawArc($cyanPen, 126, 108, 65, 54, 205, 130)
$dotBrush = New-Object System.Drawing.SolidBrush($cyan)
$g.FillEllipse($dotBrush, 151, 151, 20, 20)

$hIcon = $bmp.GetHicon()
$icon = [System.Drawing.Icon]::FromHandle($hIcon)
$stream = [System.IO.File]::Open($IconPath, [System.IO.FileMode]::Create)
$icon.Save($stream)
$stream.Close()

$g.Dispose()
$bmp.Dispose()
$icon.Dispose()
$path.Dispose()
$phone.Dispose()
$bgBrush.Dispose()
$dotBrush.Dispose()
$edgePen.Dispose()
$whitePen.Dispose()
$cyanPen.Dispose()

# Hidden launcher: double-clicking the shortcut opens AndroidBridge without
# leaving a Command Prompt window on the desktop.
$vbs = @'
Option Explicit
Dim shell, fso, root, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = Chr(34) & fso.BuildPath(root, "AndroidBridge-Lite.bat") & Chr(34)
shell.Run launcher, 0, False
'@
Set-Content -LiteralPath $VbsPath -Value $vbs -Encoding ASCII

$WScript = Join-Path $env:WINDIR "System32\wscript.exe"

function New-AndroidBridgeShortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $WScript
    $shortcut.Arguments = '"' + $VbsPath + '"'
    $shortcut.WorkingDirectory = $RepoRoot
    $shortcut.IconLocation = $IconPath + ",0"
    $shortcut.Description = "AndroidBridge - Samsung remote screen, camera and audio"
    $shortcut.Save()
}

New-AndroidBridgeShortcut $ShortcutPath
New-AndroidBridgeShortcut $StartShortcutPath

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " ANDROIDBRIDGE DESKTOP APP READY" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Desktop icon : $ShortcutPath"
Write-Host "Start Menu   : $StartShortcutPath"
Write-Host "Icon         : $IconPath"
Write-Host ""
Write-Host "Double-click AndroidBridge on the desktop." -ForegroundColor Green
