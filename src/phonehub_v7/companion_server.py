from __future__ import annotations
import base64,hashlib,hmac,json,secrets,socket,threading,time,urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dataclasses import dataclass
from pathlib import Path
PORT=47321;DEFAULT_COMMAND_PORT=47322;MAX_PACKET=2097152\nRELAY_URL="https://tmupbruwmwlrmewhoodn.supabase.co/functions/v1/phonehub-relay"
@dataclass
class Companion:
    device_id:str;device_name:str;address:str;last_seen:float;command_port:int=DEFAULT_COMMAND_PORT
    @property
    def online(self):return time.time()-self.last_seen<15
class CompanionServer:
    def __init__(self,port=PORT):
        self.port=port;self._devices={};self._lock=threading.Lock();self._thread=None
        self._keyfile=Path.home()/".phonehub"/"paired_devices.json";self._keys=self._load_keys();self._remote_status={};self._remote_thread=None
    def _load_keys(self):
        try:return json.loads(self._keyfile.read_text())
        except Exception:return {}
    def _save_keys(self):
        self._keyfile.parent.mkdir(parents=True,exist_ok=True);self._keyfile.write_text(json.dumps(self._keys,indent=2))
    def start(self):
        if self._thread and self._thread.is_alive():return
        self._thread=threading.Thread(target=self._run,name="phonehub-companion",daemon=True);self._thread.start();self._remote_thread=threading.Thread(target=self._remote_run,name="phonehub-remote",daemon=True);self._remote_thread.start()
    def devices(self):
        with self._lock:\n            local=[d for d in self._devices.values() if d.online]\n            if local:return sorted(local,key=lambda d:d.last_seen,reverse=True)\n            return [Companion(did,s.get("device_name","Android"),"REMOTE",s.get("_seen",0)) for did,s in self._remote_status.items() if time.time()-s.get("_seen",0)<30]
    def _raw_command(self,d,payload,timeout=20):
        raw=(json.dumps(payload,separators=(",",":"))+"\n").encode()
        with socket.create_connection((d.address,d.command_port),timeout=timeout) as s:
            s.sendall(raw);data=b""
            while b"\n" not in data:
                chunk=s.recv(65536)
                if not chunk:break
                data+=chunk
                if len(data)>MAX_PACKET:raise ValueError("Companion response too large")
        return json.loads(data.split(b"\n",1)[0].decode())
    def enroll(self,d):
        r=self._raw_command(d,{"type":"enroll","version":1})
        if r.get("type")!="enrolled" or not r.get("pair_key"):raise RuntimeError(r.get("message","enrollment failed"))
        self._keys[d.device_id]=r["pair_key"];self._save_keys();return r
    def command(self,d,command_type,extra=None):
        if d.device_id not in self._keys:self.enroll(d)
        ts=int(time.time());request_nonce=secrets.token_hex(16);canonical=f"{command_type}|{ts}|{request_nonce}".encode()
        key=base64.b64decode(self._keys[d.device_id]);sig=hmac.new(key,canonical,hashlib.sha256).hexdigest()
        payload={"type":command_type,"version":2,"timestamp":ts,"nonce":request_nonce,"signature":sig};payload.update(extra or {})
        plain=json.dumps(payload,separators=(",",":")).encode()
        iv=secrets.token_bytes(12);cipher=AESGCM(key).encrypt(iv,plain,None)
        wire={"type":"encrypted","version":2,"nonce":base64.b64encode(iv).decode(),"ciphertext":base64.b64encode(cipher).decode()}
        response=self._raw_command(d,wire)
        if response.get("type")!="encrypted":return response
        riv=base64.b64decode(response["nonce"]);rc=base64.b64decode(response["ciphertext"])
        return json.loads(AESGCM(key).decrypt(riv,rc,None).decode())
    def ping(self,d):return self.command(d,"ping")
    def device_status(self,d):\n        if d.address=="REMOTE":return dict(self._remote_status.get(d.device_id,{}),type="device_status")\n        return self.command(d,"device_status")
    def apps_page(self,d,offset=0,limit=50):return self.command(d,"apps",{"offset":offset,"limit":limit})
    def apps(self,d):
        items=[];offset=0
        while True:
            page=self.apps_page(d,offset,50)
            if page.get("type")!="apps_page":return page
            items.extend(page.get("apps",[]))
            if not page.get("has_more"):return {"type":"apps","apps":items,"count":len(items)}
            offset=int(page.get("next_offset",offset+50))
    def capabilities(self,d):return self.command(d,"capabilities")
    def _mailbox(self,did,key):\n        return hashlib.sha256((did+":"+base64.b64encode(key).decode()).encode()).hexdigest()\n    def _relay(self,body):\n        req=urllib.request.Request(RELAY_URL,data=json.dumps(body,separators=(",",":")).encode(),headers={"Content-Type":"application/json"},method="POST")\n        with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read().decode())\n    def _remote_run(self):\n        while True:\n            for did,key64 in list(self._keys.items()):\n                try:\n                    key=base64.b64decode(key64);box=self._mailbox(did,key);r=self._relay({"action":"receive","mailbox":box,"direction":"to_pc"})\n                    for m in r.get("messages",[]):\n                        w=m.get("payload",{})\n                        if w.get("type")!="encrypted":continue\n                        plain=AESGCM(key).decrypt(base64.b64decode(w["nonce"]),base64.b64decode(w["ciphertext"]),None);s=json.loads(plain.decode())\n                        if s.get("type")=="remote_presence" and s.get("device_id")==did:s["_seen"]=time.time();self._remote_status[did]=s\n                except Exception:pass\n            time.sleep(5)\n    def _run(self):
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
