param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Keystore = Join-Path $Root "phonehub-release.jks"
$Apk = Join-Path $Root "companion\build\outputs\apk\release\companion-release.apk"
$OutDir = Join-Path $Root "dist"
$OutApk = Join-Path $OutDir "PhoneHub-Companion-7.0.0-dev3.apk"

Write-Host "========================================"
Write-Host " PhoneHub 7 - Local Signed APK Builder"
Write-Host "========================================"

if (-not (Test-Path $Keystore)) {
    throw "Signing key not found: $Keystore"
}
if (-not (Test-Path (Join-Path $Root "gradlew.bat"))) {
    throw "gradlew.bat is missing. Make sure this script is run from the PhoneHub V7 branch."
}

$secure = Read-Host "PhoneHub signing password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $env:PHONEHUB_STORE_PASSWORD = $password
    $env:PHONEHUB_KEY_PASSWORD = $password
    $env:PHONEHUB_KEY_ALIAS = "phonehub"

    Write-Host "[1/3] Building signed Companion..."
    & (Join-Path $Root "gradlew.bat") :companion:assembleRelease
    if ($LASTEXITCODE -ne 0) { throw "Android build failed." }

    if (-not (Test-Path $Apk)) { throw "Signed APK was not produced." }
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    Copy-Item $Apk $OutApk -Force
    Write-Host "[2/3] Signed APK ready: $OutApk"

    if (Get-Command adb -ErrorAction SilentlyContinue) {
        $devices = & adb devices
        if ($devices -match "\tdevice") {
            Write-Host "[3/3] Android device detected."
            Write-Host "NOTE: the currently installed dev1 APK used GitHub's temporary debug key."
            Write-Host "The first stable-key migration requires uninstalling dev1 before installing dev3."
            Write-Host "Run INSTALL_PHONEHUB_V7.bat when ready."
        } else {
            Write-Host "[3/3] APK built. No ADB device currently connected."
        }
    } else {
        Write-Host "[3/3] APK built. ADB is not currently on PATH."
    }
}
finally {
    $env:PHONEHUB_STORE_PASSWORD = $null
    $env:PHONEHUB_KEY_PASSWORD = $null
    $env:PHONEHUB_KEY_ALIAS = $null
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $password = $null
}
