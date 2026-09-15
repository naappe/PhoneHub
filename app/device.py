import subprocess
import json
import os

CONFIG = os.path.expanduser(r"~\.phone_remote\config.json")


def run(cmd, timeout=4):
    try:
        return subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=timeout
        ).strip()
    except Exception:
        return ""


def adb(target, cmd, timeout=4):
    return run(["adb", "-s", target] + cmd, timeout=timeout)


def get_config():
    if not os.path.exists(CONFIG):
        return {}
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_available_target(cfg):
    ip = cfg.get("phone_ip", "")
    port = cfg.get("adb_port", 5555)
    usb_serial = cfg.get("usb_serial", "")
    remote_target = f"{ip}:{port}" if ip else ""

    if remote_target:
        run(["adb", "connect", remote_target], timeout=3)
        devices = run(["adb", "devices"], timeout=3)
        for line in devices.splitlines():
            if remote_target in line and "\tdevice" in line:
                return remote_target, ip, "Remote"

    devices = run(["adb", "devices"], timeout=3)
    for line in devices.splitlines():
        if "\tdevice" in line:
            serial = line.split()[0]
            if usb_serial and serial == usb_serial:
                return serial, ip, "USB"
            if not serial.startswith("emulator"):
                return serial, ip, "USB"

    return "", ip, "Offline"


def get_device():
    cfg = get_config()

    data = {
        "connected": False,
        "device": "Unknown",
        "android": "-",
        "battery": "-",
        "ip": cfg.get("phone_ip", ""),
        "target": "",
        "mode": "Offline"
    }

    target, ip, mode = get_available_target(cfg)

    data["target"] = target
    data["ip"] = ip
    data["mode"] = mode

    if not target:
        return data

    model = adb(target, ["shell", "getprop", "ro.product.model"], timeout=4)
    android = adb(target, ["shell", "getprop", "ro.build.version.release"], timeout=4)
    battery_raw = adb(target, ["shell", "dumpsys", "battery"], timeout=4)

    level = "-"
    for line in battery_raw.splitlines():
        if "level:" in line:
            level = line.split(":", 1)[1].strip()
            break

    data["device"] = model or cfg.get("device_name", "Unknown")
    data["android"] = android or "-"
    data["battery"] = level
    data["connected"] = bool(model)

    return data


if __name__ == "__main__":
    print(get_device())
