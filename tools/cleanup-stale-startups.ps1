$ErrorActionPreference = "SilentlyContinue"

# AndroidBridge startup cleanup.
# IMPORTANT: This script NEVER runs adb disconnect or adb kill-server.
# It only removes abandoned scrcpy startup clients whose child adb process is
# still pushing scrcpy-server.jar and whose parent scrcpy command belongs to
# AndroidBridge.

$all = @(Get-CimInstance Win32_Process)
$pushes = @(
    $all | Where-Object {
        $_.Name -eq "adb.exe" -and
        $_.CommandLine -match "(?i)scrcpy-server" -and
        $_.CommandLine -match "(?i)(^|[ `"'])push([ `"']|$)"
    }
)

$cleared = 0

foreach ($push in $pushes) {
    $parent = $all | Where-Object {
        $_.ProcessId -eq $push.ParentProcessId -and
        $_.Name -eq "scrcpy.exe"
    } | Select-Object -First 1

    if (-not $parent) {
        continue
    }

    $cmd = [string]$parent.CommandLine
    if ($cmd -notmatch "(?i)AndroidBridge") {
        continue
    }

    Stop-Process -Id $push.ProcessId -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $parent.ProcessId -Force -ErrorAction SilentlyContinue
    $cleared++
}

Write-Output $cleared
