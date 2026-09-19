from __future__ import annotations
import re, shutil, time
from pathlib import Path

from phonehub.core.command import CommandRunner
from phonehub.domain.models import ConnectionState, DeviceSnapshot
from phonehub.services.config_service import DeviceConfig


def parse_devices(text: str) -> dict[str, str]:
    out = {}
    for line in (text or "").splitlines():
        p = line.split()
        if len(p) >= 2 and not line.startswith("List of"):
            out[p[0]] = p[1]
    return out


class AdbService:
    def __init__(self, runner: CommandRunner):
        self.runner = runner
        self.adb = shutil.which("adb") or "adb"

    def devices(self):
        r = self.runner.run([self.adb, "devices"], 6)
        return parse_devices(r.stdout) if r.ok else {}

    def transport_state(self, cfg: DeviceConfig):
        return self.devices().get(cfg.serial, "missing")

    def wake(self, cfg: DeviceConfig):
        if not cfg.serial:
            return False
        self.runner.run([self.adb, "-s", cfg.serial, "shell", "input", "keyevent", "224"], 6)
        return True

    def connect(self, cfg: DeviceConfig):
        self.runner.run([self.adb, "start-server"], 8)
        if self.transport_state(cfg) == "device":
            return True, "Already connected"
        self.runner.run([self.adb, "connect", cfg.serial], 10)
        state = self.transport_state(cfg)
        return state == "device", ("Connected" if state == "device" else f"ADB: {state}")

    def recover(self, cfg: DeviceConfig, checks: int = 3, delay: float = 0.8):
        """Reconnect after Android lock/unlock resets ADB authorization."""
        if not cfg.serial:
            return False, "No device configured"

        state = self.transport_state(cfg)
        if state == "device":
            return True, "ADB stable"

        self.wake(cfg)
        self.runner.run([self.adb, "start-server"], 8)
        if state in {"offline", "unauthorized", "authorizing"}:
            self.runner.run([self.adb, "disconnect", cfg.serial], 6)
        self.runner.run([self.adb, "connect", cfg.serial], 12)

        stable = 0
        last_state = state
        for _ in range(max(1, checks * 3)):
            state = self.transport_state(cfg)
            if state == "device":
                stable += 1
                if stable >= checks:
                    return True, "ADB stable"
            else:
                stable = 0
                last_state = state
            time.sleep(delay)

        return False, f"ADB not stable: {last_state or state}"

    def snapshot(self, cfg: DeviceConfig):
        if not cfg.serial:
            return DeviceSnapshot(detail="Configure the phone in Device.")
        state = self.transport_state(cfg)
        if state != "device":
            mapped = ConnectionState.RECOVERING if state in {"offline", "unauthorized", "authorizing"} else ConnectionState.DISCONNECTED
            return DeviceSnapshot(state=mapped, device_name="Phone not ready", transport="Tailscale + ADB", detail=f"ADB: {state}")
        model = self.shell(cfg, "getprop ro.product.model") or "Android phone"
        android = self.shell(cfg, "getprop ro.build.version.release") or "-"
        batt = self.shell(cfg, "dumpsys battery")
        m = re.search(r"level:\s*(\d+)", batt)
        return DeviceSnapshot(
            state=ConnectionState.ONLINE,
            device_name=model,
            transport="Tailscale + ADB",
            android_version=android,
            battery_percent=int(m.group(1)) if m else None,
            detail=f"Connected • {cfg.serial}",
        )

    def shell(self, cfg: DeviceConfig, command: str):
        r = self.runner.run([self.adb, "-s", cfg.serial, "shell", command], 8)
        return r.stdout.strip() if r.ok else ""

    def key(self, cfg: DeviceConfig, keycode: int):
        return self.runner.run([self.adb, "-s", cfg.serial, "shell", "input", "keyevent", str(keycode)], 6).ok

    def screenshot(self, cfg: DeviceConfig, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        remote = "/sdcard/PhoneHub_capture.png"
        a = self.runner.run([self.adb, "-s", cfg.serial, "shell", "screencap", "-p", remote], 10)
        if not a.ok:
            return False, a.stderr or "Capture failed"
        b = self.runner.run([self.adb, "-s", cfg.serial, "pull", remote, str(dest)], 15)
        self.runner.run([self.adb, "-s", cfg.serial, "shell", "rm", remote], 5)
        return b.ok, (str(dest) if b.ok else b.stderr or "Pull failed")
