from __future__ import annotations
from dataclasses import dataclass
from phonehub.services.config_service import DeviceConfig

@dataclass(frozen=True, slots=True)
class SetupStatus:
    stage: str
    message: str
    serial: str = ""

class SetupService:
    def __init__(self, adb):
        self.adb=adb

    def inspect_usb(self) -> SetupStatus:
        devices=self.adb.devices()
        usb=[(s,state) for s,state in devices.items() if ":" not in s]
        if not usb:
            return SetupStatus("usb","Connect the phone with a USB data cable, unlock it, then press Check USB.")
        serial,state=usb[0]
        if state=="unauthorized":
            return SetupStatus("authorize","On the phone tap Allow USB debugging, optionally Always allow from this computer.",serial)
        if state!="device":
            return SetupStatus("usb",f"USB detected but ADB is {state}. Unlock the phone and reconnect USB.",serial)
        return SetupStatus("ready","USB authorized. PhoneHub can prepare this phone.",serial)

    def package_installed(self,serial:str,package:str)->bool:
        r=self.adb.runner.run([self.adb.adb,"-s",serial,"shell","pm","path",package],8)
        return r.ok and "package:" in r.stdout

    def open_tailscale(self,serial:str):
        return self.adb.runner.run([self.adb.adb,"-s",serial,"shell","monkey","-p","com.tailscale.ipn","1"],8).ok
