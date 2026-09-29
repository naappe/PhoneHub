from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import socket
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEFAULT_COMMAND_PORT = 47322
MAX_PACKET = 2097152


@dataclass
class Companion:
    device_id: str
    device_name: str
    address: str
    last_seen: float = 0.0
    command_port: int = DEFAULT_COMMAND_PORT

    @property
    def tailscale_ip(self) -> str:
        return self.address

    @property
    def online(self) -> bool:
        try:
            with socket.create_connection((self.address, self.command_port), timeout=0.6):
                return True
        except OSError:
            return False


class CompanionServer:
    """Direct Samsung Secure control over the Tailscale private network."""

    def __init__(self, port=47321):
        self.port = port  # retained for API compatibility; UDP discovery is intentionally disabled
        self._root = Path.home() / ".phonehub"
        self._keyfile = self._root / "paired_devices.json"
        self._endpoint_file = self._root / "tailscale_device.json"
        self._keys = self._load_keys()

    def _load_keys(self):
        try:
            raw = json.loads(self._keyfile.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            # Windows PowerShell 5.1 writes UTF-8 files with a BOM. utf-8-sig
            # handles both BOM and normal UTF-8 endpoint files.
            try:
                raw = json.loads(self._endpoint_file.read_text(encoding="utf-8-sig"))
                return raw if isinstance(raw, dict) else {}
            except Exception:
                return {}

    def _save_keys(self):
        self._root.mkdir(parents=True, exist_ok=True)
        self._keyfile.write_text(json.dumps(self._keys, indent=2), encoding="utf-8")

    def _load_endpoint(self):
        try:
            raw = json.loads(self._endpoint_file.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _save_endpoint(self, device: Companion):
        self._root.mkdir(parents=True, exist_ok=True)
        self._endpoint_file.write_text(
            json.dumps(
                {
                    "device_id": device.device_id,
                    "device_name": device.device_name,
                    "tailscale_ip": device.address,
                    "command_port": device.command_port,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def start(self):
        # No discovery worker is required. Tailscale is the network fabric.
        return None

    def devices(self):
        endpoint = self._load_endpoint()
        address = str(endpoint.get("tailscale_ip") or "").strip()
        if not address:
            return []
        return [
            Companion(
                str(endpoint.get("device_id") or "pending"),
                str(endpoint.get("device_name") or "Android"),
                address,
                0.0,
                int(endpoint.get("command_port") or DEFAULT_COMMAND_PORT),
            )
        ]

    def reachable(self, d, port=None, timeout=0.6):
        try:
            with socket.create_connection((d.address, port or d.command_port), timeout=timeout):
                return True
        except OSError:
            return False

    def _raw_command(self, d, payload, timeout=20):
        raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with socket.create_connection((d.address, d.command_port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(raw)
            line = s.makefile("rb").readline(MAX_PACKET + 1)
        if not line:
            raise ConnectionError("Samsung Secure returned an empty response")
        if len(line) > MAX_PACKET:
            raise ValueError("Samsung Secure response too large")
        return json.loads(line.decode("utf-8").strip())

    def enroll(self, d):
        r = self._raw_command(d, {"type": "enroll", "version": 1})
        if r.get("type") != "enrolled" or not r.get("pair_key"):
            raise RuntimeError(r.get("message", "enrollment failed"))
        actual_id = str(r.get("device_id") or d.device_id)
        d.device_id = actual_id
        if r.get("device_name"):
            d.device_name = str(r["device_name"])
        self._keys[actual_id] = r["pair_key"]
        self._save_keys()
        self._save_endpoint(d)
        return r

    def command(self, d, command_type, extra=None):
        def build_and_send():
            if d.device_id not in self._keys:
                self.enroll(d)
            ts = int(time.time())
            request_nonce = secrets.token_hex(16)
            canonical = f"{command_type}|{ts}|{request_nonce}".encode()
            key = base64.b64decode(self._keys[d.device_id])
            sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()
            payload = {
                "type": command_type,
                "version": 2,
                "timestamp": ts,
                "nonce": request_nonce,
                "signature": sig,
            }
            payload.update(extra or {})
            plain = json.dumps(payload, separators=(",", ":")).encode()
            iv = secrets.token_bytes(12)
            cipher = AESGCM(key).encrypt(iv, plain, None)
            wire = {
                "type": "encrypted",
                "version": 2,
                "nonce": base64.b64encode(iv).decode(),
                "ciphertext": base64.b64encode(cipher).decode(),
            }
            response = self._raw_command(d, wire)
            if response.get("type") != "encrypted":
                return response
            riv = base64.b64decode(response["nonce"])
            rc = base64.b64decode(response["ciphertext"])
            return json.loads(AESGCM(key).decrypt(riv, rc, None).decode())

        try:
            return build_and_send()
        except (ConnectionError, ValueError, KeyError):
            # App reinstall may rotate the Companion key while Tailscale identity stays the same.
            self._keys.pop(d.device_id, None)
            self._save_keys()
            self.enroll(d)
            return build_and_send()

    def ping(self, d):
        return self.command(d, "ping")

    def device_status(self, d):
        return self.command(d, "device_status")

    def apps_page(self, d, offset=0, limit=50):
        return self.command(d, "apps", {"offset": offset, "limit": limit})

    def apps(self, d):
        items = []
        offset = 0
        while True:
            page = self.apps_page(d, offset, 50)
            if page.get("type") != "apps_page":
                return page
            items.extend(page.get("apps", []))
            if not page.get("has_more"):
                return {"type": "apps", "apps": items, "count": len(items)}
            offset = int(page.get("next_offset", offset + 50))

    def capabilities(self, d):
        return self.command(d, "capabilities")

    def notifications(self, d):
        return self.command(d, "notifications")

    def files_list(self, d):
        return self.command(d, "files_list")

    def file_get(self, d, name):
        r = self.command(d, "file_get", {"name": name})
        if r.get("type") == "file_data" and r.get("data"):
            r["bytes"] = base64.b64decode(r["data"])
        return r

    def file_put(self, d, name, data):
        if len(data) > 1048576:
            raise ValueError("PhoneHub encrypted transfer limit is 1 MB per file")
        return self.command(d, "file_put", {"name": name, "data": base64.b64encode(data).decode()})

    def file_delete(self, d, name):
        return self.command(d, "file_delete", {"name": name})

    def screen_status(self, d):
        return self.command(d, "screen_status")

    def webrtc_offer(self, d, sdp):
        return self.command(d, "webrtc_offer", {"sdp": sdp})

    def webrtc_stop(self, d):
        return self.command(d, "webrtc_stop")

    def camera_webrtc_offer(self, d, sdp, lens="back"):
        return self.command(d, "camera_webrtc_offer", {"sdp": sdp, "lens": lens})

    def camera_webrtc_stop(self, d):
        return self.command(d, "camera_webrtc_stop")

    def policy_get(self, d, package):
        return self.command(d, "policy_get", {"package": package})

    def policy_set(self, d, package, policy):
        return self.command(d, "policy_set", {"package": package, "policy": policy})
