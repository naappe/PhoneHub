$ErrorActionPreference = "SilentlyContinue"
$selfPid = $PID

Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $selfPid -and
        ($_.Name -eq "pythonw.exe" -or $_.Name -eq "python.exe") -and
        $_.CommandLine -and
        $_.CommandLine -match "PhoneHubTailscale\.py"
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Get-Process -Name "PhoneHub" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
