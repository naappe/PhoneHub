import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\PhoneHub")
RUNTIME = ROOT / "runtime"
LOG_DIR = ROOT / "logs"
SCREENSHOT_DIR = RUNTIME / "screenshots"
SECURITY_DIR = RUNTIME / "security"
CONFIG_DIR = Path.home() / ".phone_remote"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_PORT = 5555


def no_window_flag():
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def run(args, timeout=8):
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=no_window_flag(),
        )
        return (cp.stdout or cp.stderr or "").strip()
    except Exception:
        return ""


def run_bytes(args, timeout=15):
    try:
        return subprocess.check_output(
            args,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=no_window_flag(),
        )
    except Exception:
        return b""


def spawn(args, stdout=None, stderr=None):
    try:
        return subprocess.Popen(
            args,
            stdout=stdout if stdout is not None else subprocess.DEVNULL,
            stderr=stderr if stderr is not None else subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=no_window_flag(),
        )
    except Exception:
        return None


def read_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_target(ip, port=DEFAULT_PORT):
    ip = (ip or "").strip()
    parts = ip.split(".")
    if len(parts) != 4 or parts[0] != "100":
        raise ValueError("Enter the phone Tailscale IPv4 address (100.x.x.x).")
    nums = [int(x) for x in parts]
    if any(x < 0 or x > 255 for x in nums):
        raise ValueError("Invalid IPv4 address.")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config()
    cfg["phone_ip"] = ip
    cfg["adb_port"] = int(port)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


_ACTIVE_TARGET = ""
_ACTIVE_TARGET_AT = 0.0


def configured_target():
    cfg = read_config()
    ip = str(cfg.get("phone_ip", "")).strip()
    try:
        port = int(cfg.get("adb_port", DEFAULT_PORT))
    except Exception:
        port = DEFAULT_PORT
    return f"{ip}:{port}" if ip else ""


def default_gateway():
    out = run(["route", "print", "-4", "0.0.0.0"], timeout=5)
    candidates = []
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 5 and cols[0] == "0.0.0.0" and cols[1] == "0.0.0.0":
            gw = cols[2].strip()
            if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", gw) and gw != "0.0.0.0":
                try:
                    metric = int(cols[-1])
                except Exception:
                    metric = 999999
                candidates.append((metric, gw))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def local_hotspot_target():
    cfg = read_config()
    if not cfg.get("use_local_hotspot", False):
        return ""
    gw = default_gateway()
    return f"{gw}:{DEFAULT_PORT}" if gw else ""


def _probe(serial, timeout=2):
    if not serial:
        return False
    return run(
        ["adb", "-s", serial, "shell", "echo", "PHONEHUB_OK"],
        timeout=timeout,
    ).strip() == "PHONEHUB_OK"


def target(force_refresh=False):
    """Return the configured transport without modifying ADB state."""
    local = local_hotspot_target()
    if local and _probe(local, timeout=1):
        return local
    return configured_target()


def connection_mode(serial=None):
    serial = serial or target()
    if not serial:
        return "offline"
    local = local_hotspot_target()
    if local and serial == local:
        return "local-hotspot"
    if serial.startswith("100."):
        return "tailscale"
    return "network"


def adb_devices():
    run(["adb", "start-server"], timeout=6)
    out = run(["adb", "devices"], timeout=5)
    rows = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            rows[parts[0]] = parts[1]
    return rows


def shell_probe(serial=None, timeout=3):
    serial = serial or target()
    return _probe(serial, timeout=timeout)


def ensure_remote(wait_stable=True):
    serial = target()
    if not serial:
        return False

    # Never issue 'adb disconnect' here. Disconnecting the transport kills an
    # active scrcpy/camera session. A plain adb connect is safe and idempotent.
    if not shell_probe(serial):
        run(["adb", "connect", serial], timeout=5)

    if not wait_stable:
        return shell_probe(serial)

    hits = 0
    for _ in range(10):
        if shell_probe(serial):
            hits += 1
            if hits >= 2:
                return True
        else:
            hits = 0
            run(["adb", "connect", serial], timeout=4)
        time.sleep(0.5)
    return False


def enable_tcp_on_usb():
    rows = adb_devices()
    usb = [s for s, state in rows.items() if ":" not in s and state == "device" and not s.startswith("emulator")]
    if not usb:
        return False, "Connect the phone by USB and approve USB debugging."
    serial = usb[0]
    out = run(["adb", "-s", serial, "tcpip", str(DEFAULT_PORT)], timeout=8)
    ok = "restarting in tcp mode" in out.lower() or "port: 5555" in out.lower()
    return ok, out or ("Remote ADB enabled." if ok else "Could not enable remote ADB.")


def scrcpy_path():
    candidates = [
        ROOT / "runtime" / "scrcpy" / "scrcpy.exe",
        ROOT / "tools" / "scrcpy" / "scrcpy.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return shutil.which("scrcpy")


def device_snapshot():
    serial = target()
    if not serial or not shell_probe(serial):
        return {
            "online": False,
            "target": serial,
            "mode": connection_mode(serial) if serial else "offline",
            "model": "-",
            "android": "-",
            "battery": "-",
        }
    model = run(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=4) or "-"
    android = run(["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"], timeout=4) or "-"
    battery_raw = run(["adb", "-s", serial, "shell", "dumpsys", "battery"], timeout=5)
    battery = "-"
    for line in battery_raw.splitlines():
        if "level:" in line:
            battery = line.split(":", 1)[1].strip()
            break
    return {
        "online": True,
        "target": serial,
        "mode": connection_mode(serial),
        "model": model,
        "android": android,
        "battery": battery,
    }


def screenshot():
    serial = target()
    if not serial or not shell_probe(serial):
        return False, "Phone is offline."
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"phonehub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    data = run_bytes(["adb", "-s", serial, "exec-out", "screencap", "-p"], timeout=15)
    if len(data) < 1000:
        return False, "Screenshot failed."
    path.write_bytes(data)
    return True, str(path)
