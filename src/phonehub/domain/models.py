from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ONLINE = "online"
    DEGRADED = "degraded"
    RECOVERING = "recovering"


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    state: ConnectionState = ConnectionState.DISCONNECTED
    device_name: str = "Not connected"
    transport: str = "None"
    android_version: str = "-"
    battery_percent: int | None = None
    detail: str = "Ready for setup"
