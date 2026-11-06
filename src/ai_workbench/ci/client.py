"""The UI posts explicit requests; only the detached worker owns workflow state."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
import time

from ..storage import atomic_json, read_json


class CIClient:
    def __init__(self, root, launch=None):
        self.root = Path(root)
        self.launch = launch or self._launch

    def _launch(self):
        env = dict(os.environ)
        package_source = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = package_source + os.pathsep + env.get("PYTHONPATH", "")
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
        subprocess.Popen([sys.executable, "-B", "-m", "ai_workbench.ci.worker", "--root", str(self.root)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")

    def send(self, action, **values):
        request_id = f"{time.time_ns():020d}-" + uuid.uuid4().hex
        self.launch()
        atomic_json(self.root / "commands" / (request_id + ".json"), {"action": action, **values})
        return request_id

    def snapshot(self):
        return self._read(self.root / "state.json")

    def status(self):
        return self._read(self.root / "worker-status.json")

    @staticmethod
    def _read(path):
        # Windows can briefly reject reads while the worker replaces a file.
        for attempt in range(3):
            value = read_json(path)
            if value or attempt == 2:
                return value
            time.sleep(0.01)
