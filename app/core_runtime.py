import json
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


def target():
    cfg = read_config()
    ip = str(cfg.get("phone_ip", "")).strip()
    try:
        port = int(cfg.get("adb_port", DEFAULT_PORT))
    except Exception:
        port = DEFAULT_PORT
    return f"{ip}:{port}" if ip else ""


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
    if not serial:
        return False
    return run(["adb", "-s", serial, "shell", "echo", "PHONEHUB_OK"], timeout=timeout).strip() == "PHONEHUB_OK"


def ensure_remote(wait_stable=True):
    serial = target()
    if not serial:
        return False
    if not shell_probe(serial):
        run(["adb", "disconnect", serial], timeout=2)
        run(["adb", "connect", serial], timeout=5)
    if not wait_stable:
        return shell_probe(serial)
    hits = 0
    for _ in range(8):
        if shell_probe(serial):
            hits += 1
            if hits >= 2:
                return True
        else:
            hits = 0
            run(["adb", "connect", serial], timeout=4)
        time.sleep(0.45)
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
        return {"online": False, "target": serial, "model": "-", "android": "-", "battery": "-"}
    model = run(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=4) or "-"
    android = run(["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"], timeout=4) or "-"
    battery_raw = run(["adb", "-s", serial, "shell", "dumpsys", "battery"], timeout=5)
    battery = "-"
    for line in battery_raw.splitlines():
        if "level:" in line:
            battery = line.split(":", 1)[1].strip()
            break
    return {"online": True, "target": serial, "model": model, "android": android, "battery": battery}


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
