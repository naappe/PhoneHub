from __future__ import annotations

import json
import urllib.error
import urllib.request


class PhoneHubAgentService:
    def __init__(self, port: int = 8765):
        self.port = int(port)

    def _url(self, ip: str, path: str) -> str:
        return f"http://{ip}:{self.port}{path}"

    def health(self, ip: str, timeout: float = 2.0) -> dict:
        try:
            with urllib.request.urlopen(self._url(ip, "/health"), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return {}

    def request_screen(self, ip: str, timeout: float = 3.0) -> tuple[bool, str]:
        req = urllib.request.Request(self._url(ip, "/screen/request"), data=b"", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
                return r.status in (200, 202), str(data.get("status") or "requested")
        except Exception as exc:
            return False, str(exc)

    def stop_screen(self, ip: str, timeout: float = 3.0) -> bool:
        req = urllib.request.Request(self._url(ip, "/screen/stop"), data=b"", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def frame(self, ip: str, timeout: float = 3.0) -> bytes:
        try:
            with urllib.request.urlopen(self._url(ip, "/screen/frame"), timeout=timeout) as r:
                if r.status == 200 and (r.headers.get("Content-Type") or "").startswith("image/jpeg"):
                    return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                return b""
        except Exception:
            return b""
        return b""


    def discover(self, peers, timeout: float = 1.5):
        """Find the first Tailscale peer that is actually running PhoneHub Agent."""
        for peer in peers:
            health = self.health(peer.ip, timeout=timeout)
            if health.get("service") == "phonehub-agent":
                return peer, health
        return None, {}
