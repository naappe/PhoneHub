from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from phonehub.domain.models import DeviceSnapshot


class AppState(QObject):
    device_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._device = DeviceSnapshot()

    @property
    def device(self) -> DeviceSnapshot:
        return self._device

    def set_device(self, snapshot: DeviceSnapshot) -> None:
        if snapshot == self._device:
            return
        self._device = snapshot
        self.device_changed.emit(snapshot)
