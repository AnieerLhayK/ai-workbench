"""Qt Adapter for the detached local control Module's file seam."""
import subprocess
import os
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from .lifecycle import Phase, State
from .storage import atomic_json, read_json
from .windows import DETACHED, HIDDEN


class LocalAdapter(QObject):
    def __init__(self, tool: str, config: dict, config_path: Path, parent=None):
        super().__init__(parent)
        self.root = Path(config["data_root"]) / "runtime" / tool
        self.callback = None
        self.pending_id = None
        self.observer = None
        self._last = None
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        subprocess.Popen([config["pythonw"], "-B", "-m", "ai_workbench.worker", tool, "--config", str(config_path)], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=DETACHED | HIDDEN)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def observe(self, callback):
        self.observer = callback
        callback(State(Phase.CHECKING, detail="正在检查…"))
        self._poll()
        return lambda: setattr(self, "observer", None)

    def request(self, running: bool, complete):
        self.pending_id = uuid.uuid4().hex
        self.callback = complete
        atomic_json(self.root / "requests" / f"{self.pending_id}.json", {"id": self.pending_id, "running": running})

    def _poll(self):
        record = read_json(self.root / "state.json")
        if time.time() - record.get("updated_at", 0) > 8:
            self._last = None
            if self.observer:
                self.observer(State(Phase.UNKNOWN, bool(record.get("running")), "本机控制状态未更新", "状态未确认"))
            return
        if self.pending_id:
            if record.get("completed_request") != self.pending_id:
                if record.get("active_request") == self.pending_id and self.observer:
                    self.observer(State(Phase(record["phase"]), bool(record["running"]), record.get("error"), record.get("detail", "")))
                return
            callback = self.callback
            self.pending_id = self.callback = None
            callback(record.get("error"))
        try:
            state = State(Phase(record["phase"]), bool(record["running"]), record.get("error"), record.get("detail", ""))
        except (KeyError, ValueError):
            return
        if state != self._last and self.observer:
            self._last = state
            self.observer(state)
