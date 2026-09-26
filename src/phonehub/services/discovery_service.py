from __future__ import annotations
import json
from dataclasses import dataclass
from phonehub.services.config_service import normalize_tailscale_ipv4

@dataclass(frozen=True, slots=True)
class DiscoveredPeer:
    ip: str
    name: str
    os: str = ""

class DiscoveryService:
    def __init__(self, runner):
        self.runner = runner

    def peers(self) -> list[DiscoveredPeer]:
        result = self.runner.run(["tailscale", "status", "--json"], 8)
        if not result.ok:
            return []
        try:
            data = json.loads(result.stdout)
        except (TypeError, ValueError):
            return []
        peers = []
        for peer in (data.get("Peer") or {}).values():
            if not peer.get("Online"):
                continue
            ip = next((normalize_tailscale_ipv4(x) for x in peer.get("TailscaleIPs", []) if normalize_tailscale_ipv4(x)), "")
            if ip:
                peers.append(DiscoveredPeer(ip, peer.get("HostName") or peer.get("DNSName", "").rstrip(".") or "Tailscale device", str(peer.get("OS") or "").lower()))
        android=[p for p in peers if p.os=="android"]
        return android or peers


    def android_peers(self) -> list[DiscoveredPeer]:
        """Return only online Android peers on the local Tailscale tailnet."""
        return [p for p in self.peers() if p.os == "android"]
