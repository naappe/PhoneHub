from __future__ import annotations
import json, socket, threading, time
from dataclasses import dataclass
PORT=47321; DEFAULT_COMMAND_PORT=47322; MAX_PACKET=8192
@dataclass
class Companion:
    device_id:str; device_name:str; address:str; last_seen:float; command_port:int=DEFAULT_COMMAND_PORT
    @property
    def online(self)->bool:return time.time()-self.last_seen<15
class CompanionServer:
    def __init__(self,port:int=PORT):
        self.port=port;self._devices={};self._lock=threading.Lock();self._thread=None
    def start(self):
        if self._thread and self._thread.is_alive():return
        self._thread=threading.Thread(target=self._run,name="phonehub-companion",daemon=True);self._thread.start()
    def devices(self):
        with self._lock:return sorted((d for d in self._devices.values() if d.online),key=lambda d:d.last_seen,reverse=True)
    def command(self,device:Companion,payload:dict,timeout:float=5.0)->dict:
        raw=(json.dumps(payload,separators=(",",":"))+"\n").encode()
        with socket.create_connection((device.address,device.command_port),timeout=timeout) as s:
            s.sendall(raw);data=b""
            while b"\n" not in data:
                chunk=s.recv(MAX_PACKET)
                if not chunk:break
                data+=chunk
                if len(data)>MAX_PACKET:raise ValueError("Companion response too large")
        return json.loads(data.split(b"\n",1)[0].decode())
    def ping(self,device:Companion)->dict:return self.command(device,{"type":"ping","version":1,"timestamp":int(time.time())})
    def _run(self):
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(("0.0.0.0",self.port))
        while True:
            try:
                raw,address=sock.recvfrom(MAX_PACKET);v=json.loads(raw.decode())
                if v.get("type")!="heartbeat" or v.get("version")!=1:continue
                did=str(v.get("device_id") or "").strip()
                if not did:continue
                item=Companion(did,str(v.get("device_name") or "Android"),address[0],time.time(),int(v.get("command_port") or DEFAULT_COMMAND_PORT))
                with self._lock:self._devices[did]=item
            except Exception:time.sleep(1)
