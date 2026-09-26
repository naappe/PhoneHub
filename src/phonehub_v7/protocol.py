from __future__ import annotations

from dataclasses import dataclass
import json
import time


PROTOCOL_VERSION = 1


@dataclass(frozen=True, slots=True)
class Heartbeat:
    device_id: str
    device_name: str
    timestamp: int

    def encode(self) -> bytes:
        payload = {
            "type": "heartbeat",
            "version": PROTOCOL_VERSION,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "timestamp": self.timestamp,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    @classmethod
    def now(cls, device_id: str, device_name: str) -> "Heartbeat":
        return cls(device_id=device_id, device_name=device_name, timestamp=int(time.time()))


def decode_message(raw: bytes) -> dict:
    if len(raw) > 64 * 1024:
        raise ValueError("message too large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("message must be an object")
    if value.get("version") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    return value
