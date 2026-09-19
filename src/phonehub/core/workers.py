from __future__ import annotations
from PySide6.QtCore import QObject,QRunnable,Signal,Slot
class Signals(QObject):
    result=Signal(object); error=Signal(str); finished=Signal()
class Worker(QRunnable):
    def __init__(self,fn):
        super().__init__(); self.fn=fn; self.signals=Signals()
    @Slot()
    def run(self):
        try:self.signals.result.emit(self.fn())
        except Exception as e:self.signals.error.emit(str(e))
        finally:self.signals.finished.emit()
