from __future__ import annotations

from abc import ABC, abstractmethod

from phonehub.domain.models import DeviceSnapshot


class DeviceService(ABC):
    @abstractmethod
    def snapshot(self) -> DeviceSnapshot:
        raise NotImplementedError


class OfflineDeviceService(DeviceService):
    def snapshot(self) -> DeviceSnapshot:
        return DeviceSnapshot()
