from __future__ import annotations

import time
from .companion_server import CompanionServer


def main() -> None:
    server = CompanionServer()
    server.start()
    print("[PhoneHub 7] Companion receiver ready on UDP 47321.")
    print("[PhoneHub 7] Waiting for PhoneHub Companion on the local network...")
    seen = None
    try:
        while True:
            devices = server.devices()
            current = devices[0] if devices else None
            key = (current.device_id, current.address) if current else None
            if key != seen:
                if current:
                    print(f"[PhoneHub 7] CONNECTED: {current.device_name} at {current.address}")
                else:
                    print("[PhoneHub 7] No Companion heartbeat yet.")
                seen = key
            time.sleep(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
