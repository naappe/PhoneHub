from __future__ import annotations
import re, shutil
from pathlib import Path
from phonehub.core.command import CommandRunner
from phonehub.domain.models import ConnectionState, DeviceSnapshot
from phonehub.services.config_service import DeviceConfig

def parse_devices(text: str) -> dict[str,str]:
    out={}
    for line in (text or "").splitlines():
        p=line.split()
        if len(p)>=2 and not line.startswith("List of"):
            out[p[0]]=p[1]
    return out

class AdbService:
    def __init__(self, runner: CommandRunner):
        self.runner=runner
        self.adb=shutil.which("adb") or "adb"

    def devices(self):
        r=self.runner.run([self.adb,"devices"],6)
        return parse_devices(r.stdout) if r.ok else {}

    def connect(self,cfg: DeviceConfig):
        self.runner.run([self.adb,"start-server"],8)
        if self.devices().get(cfg.serial)=="device": return True,"Already connected"
        r=self.runner.run([self.adb,"connect",cfg.serial],10)
        state=self.devices().get(cfg.serial,"missing")
        return state=="device", (f"ADB: {state}" if state!="device" else "Connected")

    def snapshot(self,cfg: DeviceConfig):
        if not cfg.serial: return DeviceSnapshot(detail="Configure the phone in Device.")
        state=self.devices().get(cfg.serial)
        if state!="device":
            mapped=ConnectionState.RECOVERING if state in {"offline","unauthorized","authorizing"} else ConnectionState.DISCONNECTED
            return DeviceSnapshot(state=mapped,device_name="Phone not ready",transport="Tailscale + ADB",detail=f"ADB: {state or 'not connected'}")
        model=self.shell(cfg,"getprop ro.product.model") or "Android phone"
        android=self.shell(cfg,"getprop ro.build.version.release") or "-"
        batt=self.shell(cfg,"dumpsys battery")
        m=re.search(r"level:\s*(\d+)",batt)
        return DeviceSnapshot(state=ConnectionState.ONLINE,device_name=model,transport="Tailscale + ADB",android_version=android,battery_percent=int(m.group(1)) if m else None,detail=f"Connected • {cfg.serial}")

    def shell(self,cfg: DeviceConfig,command: str):
        r=self.runner.run([self.adb,"-s",cfg.serial,"shell",command],8)
        return r.stdout.strip() if r.ok else ""

    def display_state(self,cfg: DeviceConfig):
        if self.devices().get(cfg.serial)!="device": return "offline"
        power=self.shell(cfg,"dumpsys power")
        window=self.shell(cfg,"dumpsys window")
        interactive=("mWakefulness=Awake" in power or "Display Power: state=ON" in power or "mInteractive=true" in power)
        locked=("mDreamingLockscreen=true" in window or "isStatusBarKeyguard=true" in window or "mShowingLockscreen=true" in window)
        if not interactive: return "screen_off"
        return "locked" if locked else "awake"

    def key(self,cfg: DeviceConfig,keycode: int):
        return self.runner.run([self.adb,"-s",cfg.serial,"shell","input","keyevent",str(keycode)],6).ok

    def screenshot(self,cfg: DeviceConfig,dest: Path):
        dest.parent.mkdir(parents=True,exist_ok=True)
        remote="/sdcard/PhoneHub_capture.png"
        a=self.runner.run([self.adb,"-s",cfg.serial,"shell","screencap","-p",remote],10)
        if not a.ok: return False,a.stderr or "Capture failed"
        b=self.runner.run([self.adb,"-s",cfg.serial,"pull",remote,str(dest)],15)
        self.runner.run([self.adb,"-s",cfg.serial,"shell","rm",remote],5)
        return b.ok,(str(dest) if b.ok else b.stderr or "Pull failed")
