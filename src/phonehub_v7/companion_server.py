from __future__ import annotations
import base64,hashlib,hmac,ipaddress,json,secrets,socket,threading,time,urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dataclasses import dataclass
from pathlib import Path
PORT=47321;DEFAULT_COMMAND_PORT=47322;MAX_PACKET=2097152
RELAY_URL="https://tmupbruwmwlrmewhoodn.supabase.co/functions/v1/phonehub-relay"
@dataclass
class Companion:
    device_id:str;device_name:str;address:str;last_seen:float;command_port:int=DEFAULT_COMMAND_PORT
    @property
    def online(self):return time.time()-self.last_seen<15
class CompanionServer:
    def __init__(self,port=PORT):
        self.port=port;self._devices={};self._lock=threading.Lock();self._thread=None
        self._keyfile=Path.home()/".phonehub"/"paired_devices.json";self._keys=self._load_keys();self._remote_status={};self._remote_thread=None;self._remote_responses={};self._remote_cv=threading.Condition()
    def _load_keys(self):
        try:return json.loads(self._keyfile.read_text())
        except Exception:return {}
    def _save_keys(self):
        self._keyfile.parent.mkdir(parents=True,exist_ok=True);self._keyfile.write_text(json.dumps(self._keys,indent=2))
    def start(self):
        if self._thread and self._thread.is_alive():return
        self._thread=threading.Thread(target=self._run,name="phonehub-companion",daemon=True);self._thread.start();self._remote_thread=threading.Thread(target=self._remote_run,name="phonehub-remote",daemon=True);self._remote_thread.start()
    def devices(self):
        with self._lock:
            local=[d for d in self._devices.values() if d.online]
            if local:return sorted(local,key=lambda d:d.last_seen,reverse=True)
            return [Companion(did,s.get("device_name","Android"),"REMOTE",s.get("_seen",0)) for did,s in self._remote_status.items() if time.time()-s.get("_seen",0)<20]
    def _raw_command(self,d,payload,timeout=20):
        raw=(json.dumps(payload,separators=(",",":"))+"\n").encode("utf-8")
        with socket.create_connection((d.address,d.command_port),timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(raw)
            line=s.makefile("rb").readline(MAX_PACKET+1)
        if not line:raise ConnectionError("Companion returned an empty response")
        if len(line)>MAX_PACKET:raise ValueError("Companion response too large")
        return json.loads(line.decode("utf-8").strip())
    def enroll(self,d):
        r=self._raw_command(d,{"type":"enroll","version":1})
        if r.get("type")!="enrolled" or not r.get("pair_key"):raise RuntimeError(r.get("message","enrollment failed"))
        actual_id=str(r.get("device_id") or d.device_id)
        self._keys[actual_id]=r["pair_key"]
        if d.device_id!=actual_id:self._keys.pop(d.device_id,None)
        self._save_keys();return r

    def enroll_address(self,address="127.0.0.1",port=DEFAULT_COMMAND_PORT):
        probe=Companion("pending","Android",address,time.time(),port)
        return self.enroll(probe)
    def command(self,d,command_type,extra=None):
        def build_and_send():
            if d.device_id not in self._keys:self.enroll(d)
            ts=int(time.time());request_nonce=secrets.token_hex(16);canonical=f"{command_type}|{ts}|{request_nonce}".encode()
            key=base64.b64decode(self._keys[d.device_id]);sig=hmac.new(key,canonical,hashlib.sha256).hexdigest()
            payload={"type":command_type,"version":2,"timestamp":ts,"nonce":request_nonce,"signature":sig};payload.update(extra or {})
            plain=json.dumps(payload,separators=(",",":")).encode()
            iv=secrets.token_bytes(12);cipher=AESGCM(key).encrypt(iv,plain,None)
            wire={"type":"encrypted","version":2,"nonce":base64.b64encode(iv).decode(),"ciphertext":base64.b64encode(cipher).decode()}
            response=self._remote_command(d,key,payload) if d.address=="REMOTE" else self._raw_command(d,wire)
            if response.get("type")!="encrypted":return response
            riv=base64.b64decode(response["nonce"]);rc=base64.b64decode(response["ciphertext"])
            return json.loads(AESGCM(key).decrypt(riv,rc,None).decode())

        try:
            return build_and_send()
        except (ConnectionError, ValueError, KeyError) as first_error:
            # A reinstall can keep the same Android ID while generating a new pair key.
            # If the phone is reachable locally, discard the stale PC key, enroll again,
            # and retry once automatically. Remote-only devices cannot be re-enrolled safely.
            if d.address=="REMOTE":
                raise first_error
            self._keys.pop(d.device_id,None)
            self._save_keys()
            self.enroll(d)
            return build_and_send()
    def ping(self,d):return self.command(d,"ping")
    def device_status(self,d):
        if d.address=="REMOTE":return dict(self._remote_status.get(d.device_id,{}),type="device_status")
        return self.command(d,"device_status")
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
    def notifications(self,d):return self.command(d,"notifications")
    def files_list(self,d):return self.command(d,"files_list")
    def file_get(self,d,name):
        r=self.command(d,"file_get",{"name":name})
        if r.get("type")=="file_data" and r.get("data"):
            r["bytes"]=base64.b64decode(r["data"])
        return r
    def file_put(self,d,name,data):
        if len(data)>1048576:raise ValueError("PhoneHub encrypted transfer limit is 1 MB per file")
        return self.command(d,"file_put",{"name":name,"data":base64.b64encode(data).decode()})
    def file_delete(self,d,name):return self.command(d,"file_delete",{"name":name})
    def screen_status(self,d):return self.command(d,"screen_status")
    def screen_prepare(self,d):return self.command(d,"screen_prepare")
    def screen_frame(self,d):return self.command(d,"screen_frame")
    def webrtc_offer(self,d,sdp):return self.command(d,"webrtc_offer",{"sdp":sdp})
    def webrtc_stop(self,d):return self.command(d,"webrtc_stop")
    def camera_webrtc_offer(self,d,sdp,lens="back"):
        return self.command(d,"camera_webrtc_offer",{"sdp":sdp,"lens":lens})
    def camera_webrtc_stop(self,d):return self.command(d,"camera_webrtc_stop")
    def policy_get(self,d,package):return self.command(d,"policy_get",{"package":package})
    def policy_set(self,d,package,policy):return self.command(d,"policy_set",{"package":package,"policy":policy})
    def _mailbox(self,did,key):
        return hashlib.sha256((did+":"+base64.b64encode(key).decode()).encode()).hexdigest()
    def _relay(self,body):
        req=urllib.request.Request(RELAY_URL,data=json.dumps(body,separators=(",",":")).encode(),headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read().decode())
    def _remote_command(self,d,key,payload,timeout=90):
        request_id=secrets.token_hex(16);payload=dict(payload);payload["_request_id"]=request_id
        iv=secrets.token_bytes(12);cipher=AESGCM(key).encrypt(iv,json.dumps(payload,separators=(",",":")).encode(),None)
        wire={"type":"encrypted","version":2,"nonce":base64.b64encode(iv).decode(),"ciphertext":base64.b64encode(cipher).decode()}
        self._relay({"action":"send","mailbox":self._mailbox(d.device_id,key),"direction":"to_phone","payload":wire})
        deadline=time.time()+timeout
        with self._remote_cv:
            while request_id not in self._remote_responses:
                remaining=deadline-time.time()
                if remaining<=0:raise TimeoutError("Remote Companion command timed out")
                self._remote_cv.wait(min(remaining,1))
            return self._remote_responses.pop(request_id)
    def _remote_run(self):
        while True:
            for did,key64 in list(self._keys.items()):
                try:
                    key=base64.b64decode(key64);box=self._mailbox(did,key);r=self._relay({"action":"receive","mailbox":box,"direction":"to_pc"})
                    for m in r.get("messages",[]):
                        w=m.get("payload",{})
                        if w.get("type")!="encrypted":continue
                        plain=AESGCM(key).decrypt(base64.b64decode(w["nonce"]),base64.b64decode(w["ciphertext"]),None);s=json.loads(plain.decode())
                        if s.get("type")=="remote_presence" and s.get("device_id")==did:
                            s["_seen"]=time.time();self._remote_status[did]=s
                            candidates=[]
                            primary=str(s.get("local_ipv4") or "").strip()
                            if primary:candidates.append(primary)
                            for value in s.get("local_ipv4_candidates",[]) or []:
                                value=str(value or "").strip()
                                if value and value not in candidates:candidates.append(value)
                            port=int(s.get("command_port") or DEFAULT_COMMAND_PORT)
                            for local_ip in candidates:
                                try:
                                    if not ipaddress.ip_address(local_ip).is_private:continue
                                    with socket.create_connection((local_ip,port),timeout=.6):pass
                                    with self._lock:self._devices[did]=Companion(did,s.get("device_name","Android"),local_ip,time.time(),port)
                                    break
                                except (ValueError,OSError):
                                    continue
                        elif s.get("_request_id"):
                            with self._remote_cv:self._remote_responses[s["_request_id"]]=s;self._remote_cv.notify_all()
                except Exception:pass
            time.sleep(1)
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
