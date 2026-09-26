from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib, re, tempfile, urllib.request, urllib.parse

TAILSCALE_PACKAGE="com.tailscale.ipn"
TAILSCALE_STABLE="https://pkgs.tailscale.com/stable/"

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
            return SetupStatus("usb","Connect the phone with a USB data cable and unlock it.")
        serial,state=usb[0]
        if state=="unauthorized":
            return SetupStatus("authorize","On the phone tap Allow USB debugging.",serial)
        if state!="device":
            return SetupStatus("usb",f"USB detected but ADB is {state}. Unlock the phone.",serial)
        return SetupStatus("ready","USB authorized.",serial)

    def package_installed(self,serial:str,package:str=TAILSCALE_PACKAGE)->bool:
        checks = [
            [self.adb.adb,"-s",serial,"shell","pm","path",package],
            [self.adb.adb,"-s",serial,"shell","cmd","package","path",package],
            [self.adb.adb,"-s",serial,"shell","pm","list","packages",package],
        ]
        for args in checks:
            r=self.adb.runner.run(args,8)
            text=(r.stdout or "").strip()
            if r.ok and (text.startswith("package:") or f"package:{package}" in text):
                return True
        return False

    def install_tailscale(self,serial:str):
        try:
            req=urllib.request.Request(TAILSCALE_STABLE,headers={"User-Agent":"PhoneHub/5"})
            with urllib.request.urlopen(req,timeout=20) as response:
                page=response.read().decode("utf-8","replace")
            matches=re.findall(r'href=["\']([^"\']*tailscale-android-universal-([0-9.]+)\.apk)["\']',page)
            if not matches:return False,"Official Tailscale stable APK was not found."
            rel,version=matches[0]
            apk_url=urllib.parse.urljoin(TAILSCALE_STABLE,rel)
            sha_url=apk_url+".sha256"
            with urllib.request.urlopen(sha_url,timeout=20) as response:
                expected=response.read().decode("ascii","replace").strip().split()[0].lower()
            dest=Path(tempfile.gettempdir())/f"phonehub-tailscale-{version}.apk"
            urllib.request.urlretrieve(apk_url,dest)
            actual=hashlib.sha256(dest.read_bytes()).hexdigest().lower()
            if actual!=expected:
                dest.unlink(missing_ok=True); return False,"Tailscale APK checksum verification failed."
            result=self.adb.runner.run([self.adb.adb,"-s",serial,"install","-r",str(dest)],120)
            dest.unlink(missing_ok=True)
            if not result.ok:return False,result.stderr or result.stdout or "APK installation failed."
            return self.package_installed(serial),f"Tailscale {version} installed."
        except Exception as exc:
            return False,f"Tailscale install failed: {exc}"

    def open_tailscale(self,serial:str):
        return self.adb.runner.run([self.adb.adb,"-s",serial,"shell","monkey","-p",TAILSCALE_PACKAGE,"1"],8).ok
