from __future__ import annotations
import json, re
from dataclasses import dataclass
from phonehub.core.command import CommandRunner
TAILSCALE_IP_RE=re.compile(r"^100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.(?:\d{1,3})\.(?:\d{1,3})$")
@dataclass(frozen=True,slots=True)
class DiscoveredPhone:
    ip:str
    name:str="Android phone"
class DiscoveryService:
    def __init__(self,runner:CommandRunner): self.runner=runner
    def tailscale_peers(self):
        r=self.runner.run(["tailscale","status","--json"],8)
        if not r.ok:return []
        try:data=json.loads(r.stdout)
        except Exception:return []
        out=[]
        for peer in (data.get("Peer") or {}).values():
            if not peer.get("Online"):continue
            ip=next((x for x in (peer.get("TailscaleIPs") or []) if TAILSCALE_IP_RE.match(x)),None)
            if ip:out.append(DiscoveredPhone(ip,peer.get("HostName") or peer.get("DNSName","").rstrip(".") or "Android phone"))
        return out
    def adb_candidates(self): return self.tailscale_peers()
