param(
    [Parameter(Position=0)]
    [ValidateSet("help","build","install","start","update","backup","remove","clean","setup","status","exe")]
    [string]$Action = "help",
    [string]$Serial = ""
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Pkg = "com.phonehub.companion"

function Title([string]$Text) {
    Write-Host ""
    Write-Host "========================================"
    Write-Host " PhoneHub V7 - $Text"
    Write-Host "========================================"
}

function VersionName {
    $f = Join-Path $Root "companion\build.gradle.kts"
    $m = [regex]::Match((Get-Content $f -Raw), 'versionName\s*=\s*"([^"]+)"')
    if (-not $m.Success) { throw "Could not read Companion version." }
    $m.Groups[1].Value
}

function AdbSerial {
    param([string]$Requested = "")
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { throw "adb not found." }
    $devices = @(& adb devices | Select-Object -Skip 1 | ForEach-Object { if ($_ -match '^([^\s]+)\s+device\s*$') { $matches[1] } })
    if ($Requested) { if ($devices -notcontains $Requested) { throw "ADB device not found: $Requested" }; return $Requested }
    if ($devices.Count -eq 0) { throw "No authorized Android device connected." }
    $usb = @($devices | Where-Object { $_ -notmatch ':\d+$' })
    if ($usb.Count -eq 1) { return $usb[0] }
    if ($devices.Count -eq 1) { return $devices[0] }
    for ($i=0; $i -lt $devices.Count; $i++) { Write-Host " [$($i+1)] $($devices[$i])" }
    $choice = [int](Read-Host "Select phone number")
    if ($choice -lt 1 -or $choice -gt $devices.Count) { throw "Invalid selection." }
    $devices[$choice-1]
}

function DoUpdate {
    Title "Update"
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "Git update failed." }
}

function DoBuild {
    Title "Build"
    $Keystore = Join-Path $Root "phonehub-release.jks"
    $Apk = Join-Path $Root "companion\build\outputs\apk\release\companion-release.apk"
    $OutDir = Join-Path $Root "dist"
    $Version = VersionName
    $OutApk = Join-Path $OutDir ("PhoneHub-Companion-{0}.apk" -f $Version)
    if (-not (Test-Path $Keystore)) { throw "Signing key not found." }
    $SdkRoot = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    $SdkManager = Join-Path $SdkRoot "cmdline-tools\latest\bin\sdkmanager.bat"
    if (-not (Test-Path $SdkManager)) { throw "Android SDK command-line tools are missing. Install them once, then run build again." }
    $env:ANDROID_HOME = $SdkRoot
    $env:ANDROID_SDK_ROOT = $SdkRoot
    "sdk.dir=$($SdkRoot -replace '\\','\\\\')" | Set-Content (Join-Path $Root "local.properties") -Encoding ASCII
    & $SdkManager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
    if ($LASTEXITCODE -ne 0) { throw "Android SDK setup failed." }
    $password = $null; $bstr = [IntPtr]::Zero
    for ($attempt=1; $attempt -le 3; $attempt++) {
        $secure = Read-Host "PhoneHub signing password" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $env:PHONEHUB_STORE_PASSWORD = $password
        & keytool -list -keystore $Keystore -storepass:env PHONEHUB_STORE_PASSWORD -alias phonehub *> $null
        if ($LASTEXITCODE -eq 0) { break }
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr); $bstr=[IntPtr]::Zero; $password=$null; $env:PHONEHUB_STORE_PASSWORD=$null
    }
    if (-not $password) { throw "Signing password verification failed." }
    try {
        $env:PHONEHUB_STORE_PASSWORD=$password; $env:PHONEHUB_KEY_PASSWORD=$password; $env:PHONEHUB_KEY_ALIAS="phonehub"
        & (Join-Path $Root "gradlew.bat") :companion:assembleRelease
        if ($LASTEXITCODE -ne 0) { throw "Android build failed." }
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
        Get-ChildItem $OutDir -Filter "PhoneHub-Companion-*.apk" -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        Copy-Item $Apk $OutApk -Force
        Write-Host "Signed APK: $OutApk"
    } finally {
        $env:PHONEHUB_STORE_PASSWORD=$null; $env:PHONEHUB_KEY_PASSWORD=$null; $env:PHONEHUB_KEY_ALIAS=$null
        if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
}

function DoInstall {
    Title "Install"
    $s = AdbSerial $Serial
    $apk = Get-ChildItem (Join-Path $Root "dist") -Filter "PhoneHub-Companion-*.apk" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $apk) { throw "No APK found. Run .\PHONEHUB.ps1 build first." }
    & adb -s $s install -r $apk.FullName
    if ($LASTEXITCODE -ne 0) { throw "APK installation failed." }
    & adb -s $s shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null
    Write-Host "Installed $($apk.Name) on $s"
}

function DoStart {
    Title "Start"
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3 is required." }
    $env:PYTHONPATH = Join-Path $Root "src"
    $env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
    python -c "import PySide6, aiortc, numpy" *> $null
    if ($LASTEXITCODE -ne 0) { python -m pip install --disable-pip-version-check "PySide6>=6.8,<7" "aiortc==1.15.0" "numpy>=2,<3" }
    python -m phonehub_v7.desktop
}

function SaveBaseline([bool]$RemoveAfter) {
    Title $(if($RemoveAfter){"Backup + Remove"}else{"Backup"})
    $s = AdbSerial $Serial
    $model = (& adb -s $s shell getprop ro.product.model).Trim()
    $safeModel = ($model -replace '[^A-Za-z0-9._-]','_')
    $out = Join-Path $Root ("phone-baselines\{0}-{1}" -f $safeModel,(Get-Date -Format "yyyyMMdd-HHmmss"))
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $manufacturer = (& adb -s $s shell getprop ro.product.manufacturer).Trim()
    $android = (& adb -s $s shell getprop ro.build.version.release).Trim()
    $sdk = (& adb -s $s shell getprop ro.build.version.sdk).Trim()
    $fingerprint = (& adb -s $s shell getprop ro.build.fingerprint).Trim()
    $androidId = (& adb -s $s shell settings get secure android_id).Trim()
    @("PhoneHub Android Baseline","Manufacturer: $manufacturer","Model: $model","Android: $android","SDK: $sdk","Android ID: $androidId","Serial: $s","Build fingerprint: $fingerprint") | Set-Content (Join-Path $out "device-info.txt") -Encoding UTF8
    & adb -s $s shell getprop | Set-Content (Join-Path $out "getprop.txt") -Encoding UTF8
    & adb -s $s shell dumpsys battery | Set-Content (Join-Path $out "battery.txt") -Encoding UTF8
    & adb -s $s shell wm size | Set-Content (Join-Path $out "display.txt") -Encoding UTF8
    $paths = @(& adb -s $s shell pm path $Pkg 2>$null | ForEach-Object { if ($_ -match '^package:(.+)$') { $matches[1].Trim() } })
    if ($paths.Count -gt 0) {
        & adb -s $s shell dumpsys package $Pkg | Set-Content (Join-Path $out "companion-package-dump.txt") -Encoding UTF8
        $apkDir=Join-Path $out "installed-apk"; New-Item -ItemType Directory -Force -Path $apkDir | Out-Null
        foreach($remote in $paths){ & adb -s $s pull $remote (Join-Path $apkDir (Split-Path $remote -Leaf)) | Out-Host }
    } else {
        "PhoneHub Companion was not installed." | Set-Content (Join-Path $out "companion-not-installed.txt") -Encoding UTF8
    }
    Write-Host "Baseline saved: $out"
    if ($RemoveAfter -and $paths.Count -gt 0) { & adb -s $s uninstall $Pkg | Out-Host }
}

function DoClean {
    Title "Clean"
    try { & (Join-Path $Root "gradlew.bat") --stop *> $null } catch {}
    foreach($p in @((Join-Path $Root ".gradle"),(Join-Path $Root "companion\build"),(Join-Path $Root "dist"),(Join-Path $Root "src\phonehub.egg-info"))){ if(Test-Path $p){Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue} }
    Get-ChildItem $Root -Directory -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {$_.Name -eq "__pycache__"} | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Cleanup complete."
}

function DoExe {
    Title "Build Windows EXE"
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3 is required." }
    python -c "import PyInstaller, PySide6" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing EXE builder..."
        python -m pip install --disable-pip-version-check pyinstaller "PySide6>=6.8,<7"
        if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller." }
    }
    $work = Join-Path $env:TEMP "phonehub-exe-build"
    $spec = Join-Path $env:TEMP "phonehub-exe-spec"
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $spec -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $work,$spec | Out-Null
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name PhoneHub --paths (Join-Path $Root "src") --distpath $Root --workpath $work --specpath $spec (Join-Path $Root "src\phonehub_v7\launcher.py")
    if ($LASTEXITCODE -ne 0) { throw "PhoneHub.exe build failed." }
    if (-not (Test-Path (Join-Path $Root "PhoneHub.exe"))) { throw "PhoneHub.exe was not created." }
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $spec -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Created: $(Join-Path $Root "PhoneHub.exe")"
}

function DoStatus {
    Title "Status"
    Write-Host "Version: $(VersionName)"
    Write-Host "Git: $(& git rev-parse --short HEAD)"
    Write-Host "Branch: $(& git branch --show-current)"
    if(Get-Command adb -ErrorAction SilentlyContinue){ & adb devices }
    git status --short
}

switch($Action){
    "update" { DoUpdate }
    "build" { DoBuild }
    "install" { DoInstall }
    "start" { DoStart }
    "backup" { SaveBaseline $false }
    "remove" { SaveBaseline $true }
    "clean" { DoClean }
    "status" { DoStatus }
    "exe" { DoExe }
    "setup" { DoUpdate; DoBuild; DoInstall; DoStart }
    default {
        Title "Master Command"
        Write-Host ".\PHONEHUB.ps1 update|build|install|start|setup|backup|remove|clean|status|exe"
    }
}