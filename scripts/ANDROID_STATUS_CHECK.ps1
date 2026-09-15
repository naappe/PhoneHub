Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "     PHONEHUB ANDROID STATUS CHECK"
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

function Explain-InstallError {
    param([string]$Text)

    Write-Host ""
    Write-Host "INSTALL ERROR DETAILS" -ForegroundColor Red
    Write-Host "---------------------" -ForegroundColor Red
    Write-Host $Text
    Write-Host ""

    if ($Text -match "INSTALL_FAILED_USER_RESTRICTED") {
        Write-Host "Reason: Phone blocked install through USB." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Open phone Settings"
        Write-Host "2. Go to Developer options"
        Write-Host "3. Turn ON Install via USB"
        Write-Host "4. Turn OFF Verify apps over USB if available"
        Write-Host "5. Unlock phone and try again"
    }
    elseif ($Text -match "INSTALL_FAILED_VERSION_DOWNGRADE") {
        Write-Host "Reason: A newer Tailscale version is already installed." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Keep the existing app, no need to install"
        Write-Host "2. Or uninstall Tailscale from phone first"
        Write-Host "3. Then run setup again"
    }
    elseif ($Text -match "INSTALL_FAILED_INSUFFICIENT_STORAGE") {
        Write-Host "Reason: Phone does not have enough storage." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Free phone storage"
        Write-Host "2. Delete unused apps/files"
        Write-Host "3. Try again"
    }
    elseif ($Text -match "INSTALL_PARSE_FAILED|Failed to parse") {
        Write-Host "Reason: APK file is broken or wrong APK type." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Delete APK inside C:\PhoneHub\apps"
        Write-Host "2. Download correct Android universal Tailscale APK again"
        Write-Host "3. Put it in C:\PhoneHub\apps"
    }
    elseif ($Text -match "device unauthorized") {
        Write-Host "Reason: USB debugging not allowed yet." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Unlock phone"
        Write-Host "2. Look for USB debugging popup"
        Write-Host "3. Tap Always allow"
        Write-Host "4. Tap OK"
    }
    elseif ($Text -match "no devices/emulators found|device .* not found") {
        Write-Host "Reason: PC cannot see the phone." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Reconnect USB cable"
        Write-Host "2. Use data cable, not charge-only cable"
        Write-Host "3. Unlock phone"
        Write-Host "4. Run adb devices"
    }
    elseif ($Text -match "Success") {
        Write-Host "Install command said Success, but package check failed." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Check phone app list for Tailscale"
        Write-Host "2. Restart phone if app does not appear"
        Write-Host "3. Run setup again"
    }
    else {
        Write-Host "Reason: Unknown install error." -ForegroundColor Yellow
        Write-Host "Fix:"
        Write-Host "1. Unlock phone"
        Write-Host "2. Check if phone asks permission"
        Write-Host "3. Check Developer options > USB debugging"
        Write-Host "4. Try install again"
    }

    Write-Host ""
}

adb start-server | Out-Null

$devicesText = adb devices
$usbLine = $devicesText -split "`r?`n" | Where-Object {
    $_ -match "\sdevice$" -and $_ -notmatch ":5555" -and $_ -notmatch "List of devices"
} | Select-Object -First 1

$remoteLine = $devicesText -split "`r?`n" | Where-Object {
    $_ -match ":5555\s+device$"
} | Select-Object -First 1

if ($usbLine) {
    $serial = ($usbLine -split "\s+")[0]

    Write-Host "USB phone connected: YES" -ForegroundColor Green
    Write-Host "USB serial: $serial"

    $model = adb -s $serial shell getprop ro.product.model
    $android = adb -s $serial shell getprop ro.build.version.release
    $battery = adb -s $serial shell dumpsys battery | Select-String "level" | Select-Object -First 1

    Write-Host "Device: $model"
    Write-Host "Android: $android"
    Write-Host "$battery"
    Write-Host ""
    Write-Host "USB Mode: READY" -ForegroundColor Green
    Write-Host "PhoneHub can open/control this phone by USB." -ForegroundColor Green
    Write-Host ""

    $tailscaleCheck = adb -s $serial shell pm list packages com.tailscale.ipn 2>$null

    if ($tailscaleCheck -match "com.tailscale.ipn") {
        Write-Host "Tailscale on phone: INSTALLED" -ForegroundColor Green
    } else {
        Write-Host "Tailscale on phone: NOT INSTALLED" -ForegroundColor Yellow
        Write-Host "Remote Mode: not ready." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "You can still use PhoneHub by USB without Tailscale." -ForegroundColor Green
        Write-Host ""

        $answer = Read-Host "Do you want to install Tailscale now? Type Y or N"

        if ($answer -eq "Y" -or $answer -eq "y") {
            $apk = Get-ChildItem "C:\PhoneHub\apps\*.apk" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1

            if (!$apk) {
                Write-Host "No Tailscale APK found in C:\PhoneHub\apps" -ForegroundColor Red
                Write-Host "Copy the Android Tailscale APK into C:\PhoneHub\apps first."
                pause
                exit
            }

            Write-Host "Installing APK: $($apk.FullName)" -ForegroundColor Yellow
            $installText = (& adb -s $serial install -r -g "$($apk.FullName)" 2>&1) -join "`n"
            Write-Host $installText

            Start-Sleep -Seconds 2
            $tailscaleCheck = adb -s $serial shell pm list packages com.tailscale.ipn 2>$null

            if ($tailscaleCheck -notmatch "com.tailscale.ipn") {
                Explain-InstallError $installText
                Write-Host ""
                Write-Host "Tailscale still not installed." -ForegroundColor Red
                Write-Host "Please check your phone and proceed setup again." -ForegroundColor Yellow
                pause
                exit
            }

            Write-Host "Tailscale installed successfully." -ForegroundColor Green
            Write-Host "Opening Tailscale on phone..." -ForegroundColor Green
            adb -s $serial shell monkey -p com.tailscale.ipn -c android.intent.category.LAUNCHER 1

            Write-Host ""
            Write-Host "NOW DO THIS ON PHONE:" -ForegroundColor Cyan
            Write-Host "1. Login to Tailscale"
            Write-Host "2. Tap Allow / OK for VPN"
            Write-Host "3. Wait until Tailscale says Connected"
            Write-Host ""
            Read-Host "After login and connected, press ENTER here"

            $tailscaleCheck = adb -s $serial shell pm list packages com.tailscale.ipn 2>$null

            if ($tailscaleCheck -notmatch "com.tailscale.ipn") {
                Write-Host ""
                Write-Host "Tailscale not installed after login step." -ForegroundColor Red
                Write-Host "Please check your phone and proceed setup again." -ForegroundColor Yellow
                pause
                exit
            }
        } else {
            Write-Host "Skipped Tailscale install." -ForegroundColor Cyan
            Write-Host "USB Mode can still work normally." -ForegroundColor Green
            pause
            exit
        }
    }

    Write-Host ""
    Write-Host "Checking Tailscale connection..." -ForegroundColor Cyan
    $tsStatus = tailscale status 2>$null
    Write-Host $tsStatus

    Write-Host ""
    $phoneIp = Read-Host "Paste phone Tailscale IP shown as android active. Leave blank to skip remote setup"

    if ($phoneIp) {
        Write-Host "Enabling remote ADB..." -ForegroundColor Yellow
        adb -s $serial tcpip 5555
        Start-Sleep -Seconds 2

        Write-Host "Connecting remote ADB..." -ForegroundColor Yellow
        adb connect "$phoneIp`:5555"
        Start-Sleep -Seconds 1

        $devicesAfter = adb devices

        if ($devicesAfter -match "$phoneIp`:5555\s+device") {
            Write-Host "Remote Mode: READY" -ForegroundColor Green
            Write-Host "PhoneHub can now work by USB and remote Tailscale." -ForegroundColor Green

            $configDir = "$env:USERPROFILE\.phone_remote"
            New-Item -ItemType Directory -Force $configDir | Out-Null

            $phoneData = @{
                phone_ip = $phoneIp
                adb_port = 5555
                device_name = "$model"
                usb_serial = "$serial"
            }

            $phoneData | ConvertTo-Json -Depth 5 | Set-Content "$configDir\config.json" -Encoding UTF8

            $phonesData = @{
                active_id = "$serial"
                phones = @(
                    @{
                        id = "$serial"
                        label = "$model"
                        device_name = "$model"
                        phone_ip = "$phoneIp"
                        adb_port = 5555
                        usb_serial = "$serial"
                        android = "$android"
                    }
                )
            }

            $phonesData | ConvertTo-Json -Depth 5 | Set-Content "$configDir\phones.json" -Encoding UTF8

            Write-Host "Saved phone profile into PhoneHub." -ForegroundColor Green
        } else {
            Write-Host "Remote ADB did not connect." -ForegroundColor Red
            Write-Host "Please check:" -ForegroundColor Yellow
            Write-Host "1. Tailscale is connected on phone"
            Write-Host "2. Correct phone Tailscale IP was pasted"
            Write-Host "3. Phone is unlocked"
            Write-Host "4. USB debugging is allowed"
            Write-Host ""
            Write-Host "USB Mode is still READY." -ForegroundColor Green
        }
    } else {
        Write-Host "Remote setup skipped." -ForegroundColor Cyan
        Write-Host "USB Mode is READY." -ForegroundColor Green
    }

} elseif ($remoteLine) {
    $target = ($remoteLine -split "\s+")[0]
    Write-Host "USB phone connected: NO" -ForegroundColor Yellow
    Write-Host "Remote phone connected: YES" -ForegroundColor Green
    Write-Host "Remote target: $target"
    Write-Host "PhoneHub can open/control this phone remotely." -ForegroundColor Green

} else {
    Write-Host "No Android phone detected." -ForegroundColor Red
    Write-Host ""
    Write-Host "To fix:" -ForegroundColor Yellow
    Write-Host "1. Connect USB cable"
    Write-Host "2. Unlock phone"
    Write-Host "3. Enable USB debugging"
    Write-Host "4. Tap Always allow / OK"
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "            CHECK FINISHED"
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""
pause

