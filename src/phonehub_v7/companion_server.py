from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass


PORT = 47321
MAX_PACKET = 8192


@dataclass
class Companion:
    device_id: str
    device_name: str
    address: str
    last_seen: float

    @property
    def online(self) -> bool:
        return time.time() - self.last_seen < 15


class CompanionServer:
    """Small zero-dependency UDP heartbeat receiver for PhoneHub Companion."""

    def __init__(self, port: int = PORT):
        self.port = port
        self._devices: dict[str, Companion] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="phonehub-companion", daemon=True)
        self._thread.start()

    def devices(self) -> list[Companion]:
        with self._lock:
            return sorted(
                (d for d in self._devices.values() if d.online),
                key=lambda d: d.last_seen,
                reverse=True,
            )

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.port))
        while True:
            try:
                raw, address = sock.recvfrom(MAX_PACKET)
                value = json.loads(raw.decode("utf-8"))
                if value.get("type") != "heartbeat" or value.get("version") != 1:
                    continue
                device_id = str(value.get("device_id") or "").strip()
                if not device_id:
                    continue
                item = Companion(
                    device_id=device_id,
                    device_name=str(value.get("device_name") or "Android"),
                    address=address[0],
                    last_seen=time.time(),
                )
                with self._lock:
                    self._devices[device_id] = item
            except Exception:
                time.sleep(1)
