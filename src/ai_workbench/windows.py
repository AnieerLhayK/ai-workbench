"""Windows process identity and the two concrete launch/stop implementations."""
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


@dataclass(frozen=True)
class Identity:
    pid: int
    created: str
    executable: str
    command: str

    @classmethod
    def from_row(cls, row):
        return cls(int(row["ProcessId"]), str(row["CreationDate"]), row.get("ExecutablePath") or "", row.get("CommandLine") or "")


def canonical(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class WindowsProcesses:
    def __init__(self, config: dict):
        self.config = config

    def _query(self, script: str) -> list[Identity]:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + script],
            capture_output=True, encoding="utf-8-sig", errors="replace", timeout=12, creationflags=HIDDEN,
        )
        if result.returncode:
            raise RuntimeError("无法读取本机进程状态")
        rows = json.loads(result.stdout.strip() or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        return [Identity.from_row(row) for row in rows]

    def identity(self, pid: int) -> Identity | None:
        rows = self._query(f"Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}' | Select-Object ProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress")
        return rows[0] if rows else None

    def matches(self, tool: str, identity: Identity) -> bool:
        command = identity.command.replace("\\", "/")
        executable = canonical(identity.executable) if identity.executable else ""
        if tool == "commander":
            return executable == canonical(self.config["node"]) and bool(re.search(
                r"@wonderwhy-er/desktop-commander/dist/index\.js[\"']?\s+remote(?:\s|$)", command,
            ))
        # Windows venv launchers create a base-interpreter child. The module
        # command plus the profile PID record disambiguates that child.
        configured_python = Path(self.config["hermes_pythonw"])
        base_python = configured_python.parent.parent / "pyvenv.cfg"
        allowed = {canonical(str(configured_python))}
        if base_python.is_file():
            for line in base_python.read_text(encoding="utf-8").splitlines():
                if line.startswith("home = "):
                    home = Path(line.partition(" = ")[2])
                    allowed.update(canonical(str(home / name)) for name in ("python.exe", "pythonw.exe"))
        return bool(re.search(r"(?:^|\s)-m\s+hermes_cli\.main\s+gateway\s+run(?:\s|$)", command)) and executable in allowed and self._hermes_record_matches(identity)

    def _hermes_record_matches(self, identity: Identity) -> bool:
        from .storage import read_json
        record = read_json(Path(self.config["hermes_home"]) / "gateway.pid")
        if record.get("pid") != identity.pid:
            return False
        # A matching current command and the current profile's PID record
        # permit the base-interpreter child; never adopt another profile.
        return record.get("kind") == "hermes-gateway"

    def discover(self, tool: str) -> Identity | None:
        pattern = "@wonderwhy-er.*desktop-commander.*index\\.js.*remote" if tool == "commander" else "hermes_cli\\.main\\s+gateway\\s+run"
        rows = self._query("Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(node|python|pythonw)\\.exe$' -and $_.CommandLine -match '" + pattern + "' } | Select-Object ProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress")
        matches = [row for row in rows if self.matches(tool, row)]
        if tool == "hermes":
            recorded = [row for row in matches if self._hermes_record_matches(row)]
            if recorded:
                matches = recorded
        if len(matches) > 1:
            raise RuntimeError("检测到多个匹配实例，无法安全选择控制目标")
        return matches[0] if matches else None

    def launch(self, tool: str) -> subprocess.Popen:
        if tool == "commander":
            command = f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c ""{self.config["npx"]}" -y @wonderwhy-er/desktop-commander@latest remote"'
            env = dict(os.environ)
            if any(env.get(name) for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")):
                # Modern Node fetch requires opt-in to honor inherited proxies.
                env.setdefault("NODE_USE_ENV_PROXY", "1")
            return subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=HIDDEN | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        env = dict(os.environ, HERMES_HOME=self.config["hermes_home"], PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HERMES_GATEWAY_DETACHED="1", VIRTUAL_ENV=str(Path(self.config["hermes_pythonw"]).parent.parent))
        return subprocess.Popen([self.config["hermes_pythonw"], "-m", "hermes_cli.main", "gateway", "run"], cwd=self.config["hermes_home"], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=HIDDEN | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    def kill_exact(self, identity: Identity) -> None:
        current = self.identity(identity.pid)
        if current != identity:
            raise RuntimeError("进程身份已变化，未执行停止")
        result = subprocess.run(["taskkill.exe", "/PID", str(identity.pid), "/T", "/F"], capture_output=True, creationflags=HIDDEN, timeout=15)
        if result.returncode and self.identity(identity.pid) is not None:
            raise RuntimeError("目标进程未能停止")

    def stop(self, tool: str, identity: Identity) -> None:
        if self.identity(identity.pid) != identity or not self.matches(tool, identity):
            raise RuntimeError("进程身份已变化，未执行停止")
        if tool == "commander":
            self.kill_exact(identity)
        else:
            env = dict(os.environ, HERMES_HOME=self.config["hermes_home"], PYTHONIOENCODING="utf-8")
            result = subprocess.run([self.config["hermes_exe"], "gateway", "stop"], cwd=self.config["hermes_home"], env=env, capture_output=True, timeout=25, creationflags=HIDDEN)
            if result.returncode:
                raise RuntimeError("Hermes 停止命令失败")
