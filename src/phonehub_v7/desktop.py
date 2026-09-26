from __future__ import annotations
import time
from .companion_server import CompanionServer

def gb(n): return f"{n/1073741824:.1f} GB"

def main():
    server=CompanionServer();server.start()
    print("[PhoneHub 7] Secure Companion receiver ready on UDP 47321.")
    print("[PhoneHub 7] Waiting for PhoneHub Companion on the local network...")
    seen=None
    try:
        while True:
            devices=server.devices();current=devices[0] if devices else None;key=(current.device_id,current.address) if current else None
            if key!=seen:
                if current:
                    print(f"[PhoneHub 7] DISCOVERED: {current.device_name} at {current.address}")
                    try:
                        r=server.ping(current)
                        if r.get("type")=="pong":
                            print(f"[PhoneHub 7] AUTHENTICATED: {r.get('device_name')} | Android {r.get('android_version')} | SDK {r.get('sdk')}")
                            s=server.device_status(current)
                            if s.get("type")=="device_status":
                                charge="charging" if s.get("charging") else "not charging"
                                print(f"[PhoneHub 7] STATUS: Battery {s.get('battery_percent')}% ({charge}) | Network {s.get('network')}")
                                print(f"[PhoneHub 7] STORAGE: {gb(s.get('storage_free',0))} free / {gb(s.get('storage_total',0))} total")
                                print(f"[PhoneHub 7] MEMORY: {gb(s.get('memory_free',0))} free / {gb(s.get('memory_total',0))} total")
                        else:print(f"[PhoneHub 7] AUTH FAILED: {r.get('message','unknown error')}")
                    except Exception as e:print(f"[PhoneHub 7] SECURE CHANNEL NOT READY: {e}")
                else:print("[PhoneHub 7] No Companion heartbeat yet.")
                seen=key
            time.sleep(2)
    except KeyboardInterrupt:pass
if __name__=="__main__":main()
