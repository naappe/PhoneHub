param(
    [ValidateSet("setup","status","start","stop","remove","show")]
    [string]$Action = "status",
    [string]$PhonePublicKey = "",
    [int]$ListenPort = 51820
)

$ErrorActionPreference = "Stop"
$Root = "C:\PhoneHub\runtime\vpn"
$ConfigPath = Join-Path $Root "PhoneHubVPN.conf"
$PrivateKeyPath = Join-Path $Root "pc_private.key"
$PublicKeyPath = Join-Path $Root "pc_public.key"
$TunnelName = "PhoneHubVPN"

New-Item -ItemType Directory -Force -Path $Root | Out-Null

function Find-WireGuardExe {
    $candidates = @(
        "$env:ProgramFiles\WireGuard\wireguard.exe",
        "$env:ProgramFiles(x86)\WireGuard\wireguard.exe",
        "wireguard.exe"
    )
    foreach ($p in $candidates) {
        try {
            if (Test-Path $p) { return (Resolve-Path $p).Path }
            $cmd = Get-Command $p -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        } catch {}
    }
    return $null
}

function Find-WgExe {
    $candidates = @(
        "$env:ProgramFiles\WireGuard\wg.exe",
        "$env:ProgramFiles(x86)\WireGuard\wg.exe",
        "wg.exe"
    )
    foreach ($p in $candidates) {
        try {
            if (Test-Path $p) { return (Resolve-Path $p).Path }
            $cmd = Get-Command $p -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        } catch {}
    }
    return $null
}

function Ensure-Keys {
    $wg = Find-WgExe
    if (-not $wg) {
        throw "WireGuard command-line tool wg.exe was not found. Install WireGuard for Windows first."
    }

    if (-not (Test-Path $PrivateKeyPath)) {
        $private = (& $wg genkey).Trim()
        if (-not $private) { throw "Could not generate PC WireGuard private key." }
        Set-Content -Path $PrivateKeyPath -Value $private -NoNewline
    }

    $private = (Get-Content $PrivateKeyPath -Raw).Trim()
    $public = ($private | & $wg pubkey).Trim()
    Set-Content -Path $PublicKeyPath -Value $public -NoNewline
    return @{
        Private = $private
        Public = $public
    }
}

function Write-Config {
    param([string]$PhoneKey)

    $keys = Ensure-Keys

    $lines = @(
        "[Interface]",
        "PrivateKey = $($keys.Private)",
        "Address = 10.77.0.1/24",
        "ListenPort = $ListenPort"
    )

    if ($PhoneKey) {
        $lines += @(
            "",
            "[Peer]",
            "PublicKey = $PhoneKey",
            "AllowedIPs = 10.77.0.2/32"
        )
    }

    Set-Content -Path $ConfigPath -Value ($lines -join [Environment]::NewLine) -Encoding ascii

    Write-Host ""
    Write-Host "PhoneHub VPN PC config ready." -ForegroundColor Green
    Write-Host "PC tunnel IP : 10.77.0.1"
    Write-Host "Phone tunnel : 10.77.0.2"
    Write-Host "Listen port  : $ListenPort"
    Write-Host "PC public key: $($keys.Public)"
    Write-Host "Config       : $ConfigPath"
    if (-not $PhoneKey) {
        Write-Host ""
        Write-Host "Phone public key not supplied yet." -ForegroundColor Yellow
        Write-Host "Run setup again with:"
        Write-Host "  .\vpn\PhoneHubVPN.ps1 setup -PhonePublicKey '<PHONE_PUBLIC_KEY>'"
    }
}

function Install-Tunnel {
    $wireguard = Find-WireGuardExe
    if (-not $wireguard) {
        throw "WireGuard for Windows was not found. Install WireGuard for Windows first."
    }
    if (-not (Test-Path $ConfigPath)) {
        throw "Config not found. Run setup first."
    }

    try {
        & $wireguard /uninstalltunnelservice $TunnelName 2>$null | Out-Null
    } catch {}

    & $wireguard /installtunnelservice $ConfigPath
    Start-Sleep -Seconds 2
    Write-Host "PhoneHub VPN tunnel service installed." -ForegroundColor Green
}

function Stop-Tunnel {
    $wireguard = Find-WireGuardExe
    if (-not $wireguard) {
        throw "WireGuard for Windows was not found."
    }
    & $wireguard /uninstalltunnelservice $TunnelName
    Write-Host "PhoneHub VPN tunnel stopped." -ForegroundColor Yellow
}

function Show-Status {
    $wg = Find-WgExe
    Write-Host "PhoneHub VPN" -ForegroundColor Cyan
    Write-Host "Config: $ConfigPath"
    if (Test-Path $PublicKeyPath) {
        Write-Host "PC public key: $((Get-Content $PublicKeyPath -Raw).Trim())"
    }
    if ($wg) {
        try {
            & $wg show
        } catch {
            Write-Host "No active WireGuard tunnel detected."
        }
    } else {
        Write-Host "WireGuard tools are not installed." -ForegroundColor Yellow
    }
}

switch ($Action) {
    "setup" {
        Write-Config -PhoneKey $PhonePublicKey
    }
    "start" {
        Install-Tunnel
    }
    "stop" {
        Stop-Tunnel
    }
    "remove" {
        try { Stop-Tunnel } catch {}
        Remove-Item -Recurse -Force $Root -ErrorAction SilentlyContinue
        Write-Host "PhoneHub VPN runtime files removed."
    }
    "show" {
        if (Test-Path $ConfigPath) { Get-Content $ConfigPath }
        else { Write-Host "Config not created yet." }
    }
    default {
        Show-Status
    }
}
