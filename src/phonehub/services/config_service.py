from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import json
import os
from pathlib import Path


TAILSCALE_IPV4 = ipaddress.ip_network("100.64.0.0/10")


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    phone_ip: str = ""
    adb_port: int = 5555

    @property
    def serial(self) -> str:
        return f"{self.phone_ip}:{self.adb_port}" if self.phone_ip else ""


def normalize_tailscale_ipv4(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return ""
    if address.version != 4 or address not in TAILSCALE_IPV4:
        return ""
    return str(address)


class ConfigService:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            base = Path(os.getenv("APPDATA", Path.home()))
            path = base / "PhoneHub" / "config.json"
        self.path = path

    def load(self) -> DeviceConfig:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return DeviceConfig()

        ip = normalize_tailscale_ipv4(data.get("phone_ip"))
        try:
            port = int(data.get("adb_port", 5555))
        except (TypeError, ValueError):
            port = 5555
        if not 1 <= port <= 65535:
            port = 5555
        return DeviceConfig(phone_ip=ip, adb_port=port)

    def save(self, config: DeviceConfig) -> DeviceConfig:
        ip = normalize_tailscale_ipv4(config.phone_ip)
        if not ip:
            raise ValueError("Enter a valid Tailscale IPv4 address (100.64.0.0/10).")
        if not 1 <= int(config.adb_port) <= 65535:
            raise ValueError("ADB port must be between 1 and 65535.")

        clean = DeviceConfig(ip, int(config.adb_port))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(clean), indent=2), encoding="utf-8")
        return clean
