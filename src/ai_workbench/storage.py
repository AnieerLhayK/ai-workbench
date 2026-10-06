"""Small local file protocol, with atomic writes and process-held locks."""
import json
import os
import tempfile
import time
from pathlib import Path


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8-sig"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.025)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProcessLock:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+b")
        self.acquired = False
        self.stream.seek(0)
        if path.stat().st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError:
            self.stream.close()

    def close(self):
        if self.acquired:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.acquired = False


def load_config(path: Path) -> dict:
    config = read_json(path)
    required = ("data_root", "pythonw", "npx", "node", "hermes_home", "hermes_pythonw", "hermes_exe")
    if not all(isinstance(config.get(key), str) and config[key] for key in required):
        raise ValueError("本机配置缺失或格式不完整")
    for key in required:
        if not Path(config[key]).is_absolute():
            raise ValueError(f"配置 {key} 必须为绝对路径")
    for key in ("pythonw", "npx", "node", "hermes_pythonw", "hermes_exe"):
        if not Path(config[key]).is_file():
            raise ValueError(f"运行环境缺失：{key}")
    return config
