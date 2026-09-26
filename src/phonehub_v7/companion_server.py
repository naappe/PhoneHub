from __future__ import annotations
import base64,hashlib,hmac,json,secrets,socket,threading,time
from dataclasses import dataclass
from pathlib import Path
PORT=47321;DEFAULT_COMMAND_PORT=47322;MAX_PACKET=8192
@dataclass
class Companion:
    device_id:str;device_name:str;address:str;last_seen:float;command_port:int=DEFAULT_COMMAND_PORT
    @property
    def online(self):return time.time()-self.last_seen<15
class CompanionServer:
    def __init__(self,port=PORT):
        self.port=port;self._devices={};self._lock=threading.Lock();self._thread=None
        self._keyfile=Path.home()/".phonehub"/"paired_devices.json";self._keys=self._load_keys()
    def _load_keys(self):
        try:return json.loads(self._keyfile.read_text())
        except Exception:return {}
    def _save_keys(self):
        self._keyfile.parent.mkdir(parents=True,exist_ok=True);self._keyfile.write_text(json.dumps(self._keys,indent=2))
    def start(self):
        if self._thread and self._thread.is_alive():return
        self._thread=threading.Thread(target=self._run,name="phonehub-companion",daemon=True);self._thread.start()
    def devices(self):
        with self._lock:return sorted((d for d in self._devices.values() if d.online),key=lambda d:d.last_seen,reverse=True)
    def _raw_command(self,d,payload,timeout=5):
        raw=(json.dumps(payload,separators=(",",":"))+"\n").encode()
        with socket.create_connection((d.address,d.command_port),timeout=timeout) as s:
            s.sendall(raw);data=b""
            while b"\n" not in data:
                chunk=s.recv(MAX_PACKET)
                if not chunk:break
                data+=chunk
                if len(data)>MAX_PACKET:raise ValueError("Companion response too large")
        return json.loads(data.split(b"\n",1)[0].decode())
    def enroll(self,d):
        r=self._raw_command(d,{"type":"enroll","version":1})
        if r.get("type")!="enrolled" or not r.get("pair_key"):raise RuntimeError(r.get("message","enrollment failed"))
        self._keys[d.device_id]=r["pair_key"];self._save_keys();return r
    def command(self,d,command_type):
        if d.device_id not in self._keys:self.enroll(d)
        ts=int(time.time());nonce=secrets.token_hex(16);canonical=f"{command_type}|{ts}|{nonce}".encode()
        key=base64.b64decode(self._keys[d.device_id]);sig=hmac.new(key,canonical,hashlib.sha256).hexdigest()
        return self._raw_command(d,{"type":command_type,"version":1,"timestamp":ts,"nonce":nonce,"signature":sig})
    def ping(self,d):return self.command(d,"ping")
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
