$ErrorActionPreference = "SilentlyContinue"
$selfPid = $PID

# Stop every PhoneHub Python generation before launching the current app.
# The previous script only matched PhoneHubTailscale.py, so PhoneHubCore.py
# instances were left running in the background and could launch duplicate
# scrcpy windows and compete for the same ADB transport.
Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $selfPid -and
        ($_.Name -eq "pythonw.exe" -or $_.Name -eq "python.exe") -and
        $_.CommandLine -and
        (
            $_.CommandLine -match "PhoneHubCore\.py" -or
            $_.CommandLine -match "PhoneHubTailscale\.py" -or
            $_.CommandLine -match "PhoneHub\.py" -or
            $_.CommandLine -match "PhoneHubLink\.py"
        )
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Stop only scrcpy processes launched from the PhoneHub bundled runtime or
# carrying a PhoneHub window title. This clears stale black/disconnected
# windows without killing an unrelated system scrcpy installation.
Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "scrcpy.exe" -and
        $_.CommandLine -and
        (
            $_.CommandLine -match "C:\\PhoneHub\\runtime\\scrcpy" -or
            $_.CommandLine -match "window-title=PhoneHub"
        )
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Get-Process -Name "PhoneHub" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
