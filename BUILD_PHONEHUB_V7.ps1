param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Keystore = Join-Path $Root "phonehub-release.jks"
$Apk = Join-Path $Root "companion\build\outputs\apk\release\companion-release.apk"
$OutDir = Join-Path $Root "dist"
$OutApk = Join-Path $OutDir "PhoneHub-Companion-7.0.0-dev9.apk"
$SdkRoot = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$CmdRoot = Join-Path $SdkRoot "cmdline-tools"
$Latest = Join-Path $CmdRoot "latest"
$SdkManager = Join-Path $Latest "bin\sdkmanager.bat"

Write-Host "========================================"
Write-Host " PhoneHub 7 - Automatic Local Builder"
Write-Host "========================================"

if (-not (Test-Path $Keystore)) { throw "Signing key not found: $Keystore" }
if (-not (Test-Path (Join-Path $Root "gradlew.bat"))) { throw "gradlew.bat is missing." }

# Bootstrap Google's Android command-line SDK only when it is missing.
if (-not (Test-Path $SdkManager)) {
    Write-Host "[Setup] Android SDK not found. Installing command-line tools automatically..."
    $zip = Join-Path $env:TEMP "phonehub-android-tools.zip"
    $tmp = Join-Path $env:TEMP "phonehub-android-tools"
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $CmdRoot,$tmp | Out-Null

    $page = Invoke-WebRequest "https://developer.android.com/studio"
    $match = [regex]::Match($page.Content, 'https://dl\.google\.com/android/repository/commandlinetools-win-[0-9]+_latest\.zip')
    if (-not $match.Success) { throw "Could not locate Google's current Android command-line tools download." }

    Invoke-WebRequest $match.Value -OutFile $zip
    Expand-Archive $zip -DestinationPath $tmp -Force
    Remove-Item $Latest -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $Latest | Out-Null
    Copy-Item (Join-Path $tmp "cmdline-tools\*") $Latest -Recurse -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

$env:ANDROID_HOME = $SdkRoot
$env:ANDROID_SDK_ROOT = $SdkRoot
"sdk.dir=$($SdkRoot -replace '\\','\\')" | Set-Content (Join-Path $Root "local.properties") -Encoding ASCII

Write-Host "[Setup] Installing/verifying Android SDK 35..."
$licenses = (1..20 | ForEach-Object { "y" }) -join [Environment]::NewLine
$licenses | & $SdkManager --licenses | Out-Null
& $SdkManager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
if ($LASTEXITCODE -ne 0) { throw "Android SDK setup failed." }

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
    Write-Host "[3/3] Build complete."
}
finally {
    $env:PHONEHUB_STORE_PASSWORD = $null
    $env:PHONEHUB_KEY_PASSWORD = $null
    $env:PHONEHUB_KEY_ALIAS = $null
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $password = $null
}
