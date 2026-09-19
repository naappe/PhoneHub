from __future__ import annotations
import shutil, subprocess
from pathlib import Path
from phonehub.services.config_service import DeviceConfig

class MediaSessionManager:
    def __init__(self):
        self.process: subprocess.Popen|None=None
        self.kind=""
        self.scrcpy=shutil.which("scrcpy")

    @property
    def active(self): return self.process is not None and self.process.poll() is None

    def stop(self):
        if self.active:
            self.process.terminate()
            try: self.process.wait(3)
            except subprocess.TimeoutExpired: self.process.kill()
        self.process=None; self.kind=""

    def _start(self,args:list[str],kind:str):
        if not self.scrcpy: return False,"scrcpy.exe not found in Windows PATH"
        self.stop()
        flags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,"CREATE_NO_WINDOW") else 0
        try:
            self.process=subprocess.Popen([self.scrcpy,*args],creationflags=flags)
            self.kind=kind
            return True,f"{kind.title()} opened"
        except Exception as e: return False,str(e)

    def screen(self,cfg:DeviceConfig,max_size=1080,fps=30):
        return self._start(["-s",cfg.serial,"--no-audio",f"--max-size={max_size}",f"--max-fps={fps}","--stay-awake","--window-title=PhoneHub Screen"],"screen")

    def camera(self,cfg:DeviceConfig,facing:str):
        return self._start(["-s",cfg.serial,"--video-source=camera",f"--camera-facing={facing}","--camera-size=1280x720","--camera-fps=30","--no-audio",f"--window-title=PhoneHub {facing.title()} Camera"],"camera")
