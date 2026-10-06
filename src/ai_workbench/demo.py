"""Qt timer simulation; never launches processes or accesses accounts."""
from PySide6.QtCore import QObject, QTimer

from .lifecycle import Completion, State


class DemoAdapter(QObject):
    def __init__(self, parent: QObject | None = None, delay_ms: int = 900):
        super().__init__(parent)
        self.delay_ms = delay_ms
        self.fail_next = False

    def observe(self, callback):
        callback(State())
        return lambda: None

    def request(self, running: bool, complete: Completion) -> None:
        error = "模拟操作失败，请重试。" if self.fail_next else None
        self.fail_next = False
        QTimer.singleShot(self.delay_ms, self, lambda: complete(error))
