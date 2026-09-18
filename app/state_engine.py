import shutil
import subprocess
from datetime import datetime, timezone


def _no_window_flag():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args, timeout=6):
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_no_window_flag(),
        )
        return (cp.stdout or cp.stderr or "").strip()
    except Exception:
        return ""


def _adb_devices():
    out = _run(["adb", "devices"], timeout=5)
    devices = []
    unauthorized = []
    for line in out.splitlines():
        if "\tdevice" in line:
            devices.append(line.split()[0])
        elif "\tunauthorized" in line:
            unauthorized.append(line.split()[0])
    return devices, unauthorized


def _fastboot_devices():
    if not shutil.which("fastboot"):
        return []
    out = _run(["fastboot", "devices"], timeout=5)
    return [line.split()[0] for line in out.splitlines() if line.strip()]


def _adb(serial, *parts, timeout=5):
    return _run(["adb", "-s", serial, *parts], timeout=timeout)


def detect_device_state():
    timestamp = datetime.now(timezone.utc).isoformat()
    fastboot = _fastboot_devices()
    if fastboot:
        return {
            "timestamp": timestamp,
            "mode": "FASTBOOT",
            "transport": "USB",
            "serial": fastboot[0],
            "detail": "Device detected by Fastboot.",
            "adb_available": False,
            "fastboot_available": True,
        }

    devices, unauthorized = _adb_devices()
    if devices:
        serial = devices[0]
        transport = "REMOTE" if ":" in serial else "USB"
        bootmode = _adb(serial, "shell", "getprop", "ro.bootmode").lower()
        build_type = _adb(serial, "shell", "getprop", "ro.build.type").lower()
        recovery_markers = ("recovery", "rescue")
        recovery = any(marker in bootmode for marker in recovery_markers)

        return {
            "timestamp": timestamp,
            "mode": "RECOVERY_ADB" if recovery else "ANDROID_ADB",
            "transport": transport,
            "serial": serial,
            "detail": (
                f"ADB authorized. bootmode={bootmode or 'unknown'}, "
                f"build_type={build_type or 'unknown'}"
            ),
            "adb_available": True,
            "fastboot_available": False,
        }

    if unauthorized:
        serial = unauthorized[0]
        return {
            "timestamp": timestamp,
            "mode": "ADB_UNAUTHORIZED",
            "transport": "REMOTE" if ":" in serial else "USB",
            "serial": serial,
            "detail": "ADB device found but authorization is pending on the phone.",
            "adb_available": False,
            "fastboot_available": False,
        }

    return {
        "timestamp": timestamp,
        "mode": "OFFLINE",
        "transport": "NONE",
        "serial": "",
        "detail": "No authorized ADB or Fastboot device detected.",
        "adb_available": False,
        "fastboot_available": False,
    }


def state_summary(state, previous=None):
    mode = state.get("mode", "UNKNOWN")
    transport = state.get("transport", "NONE")
    serial = state.get("serial") or "-"
    detail = state.get("detail") or "-"

    lines = [
        "PHONEHUB DEVICE STATE",
        "",
        f"Mode: {mode}",
        f"Transport: {transport}",
        f"Serial: {serial}",
        f"ADB available: {'Yes' if state.get('adb_available') else 'No'}",
        f"Fastboot available: {'Yes' if state.get('fastboot_available') else 'No'}",
        f"Detail: {detail}",
    ]

    if previous and previous.get("mode") != mode:
        lines.extend([
            "",
            f"STATE TRANSITION: {previous.get('mode', 'UNKNOWN')} -> {mode}",
        ])

    lines.extend([
        "",
        "Automatic state logic:",
        "ANDROID_ADB -> normal PhoneHub controls available",
        "RECOVERY_ADB -> recovery diagnostics only",
        "FASTBOOT -> Fastboot diagnostics",
        "ADB_UNAUTHORIZED -> wait for on-device authorization",
        "OFFLINE -> no device commands",
    ])
    return "\n".join(lines)
