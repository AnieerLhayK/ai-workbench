"""Project terminal dispatch Module; completion means handoff, never agent readiness."""
import base64
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer


@dataclass(frozen=True)
class LaunchRequest:
    tool: str
    project: str
    mode: str


@dataclass(frozen=True)
class DispatchState:
    pending: bool = False
    project: str = ""
    error: str | None = None
    dispatched: bool = False


def project_path(value: str) -> str:
    if not isinstance(value, str) or not value or not Path(value).is_absolute() or not Path(value).is_dir():
        raise ValueError("请选择有效的项目目录")
    return str(Path(value).resolve())


def recent_projects(values) -> list[str]:
    """Keep missing directories visible so a moved project is not silently substituted."""
    if not isinstance(values, list):
        return []
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            continue
        key = os.path.normcase(os.path.abspath(value))
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result[:10]


def remember_project(project: str, values) -> list[str]:
    return recent_projects([project, *recent_projects(values)])


class TerminalLauncher:
    """Small launch/observe Interface; adapters complete on the GUI thread."""
    def __init__(self, adapter):
        self.adapter = adapter
        self.state = DispatchState()
        self.observers = []

    def observe(self, callback):
        self.observers.append(callback)
        callback(self.state)
        return lambda: self.observers.remove(callback)

    def _emit(self, state):
        self.state = state
        for callback in tuple(self.observers):
            callback(state)

    def launch(self, tool: str, project: str, mode: str) -> bool:
        if self.state.pending:
            return False
        try:
            if tool not in ("codex", "claude") or mode not in ("new", "resume"):
                raise ValueError("未知终端启动请求")
            request = LaunchRequest(tool, project_path(project), mode)
        except ValueError as error:
            self._emit(DispatchState(error=str(error)))
            return False
        return self._dispatch(request)

    def _dispatch(self, request):
        """Dispatch a validated immutable snapshot through the adapter Seam."""
        self._emit(DispatchState(pending=True, project=request.project))
        completed = False

        def complete(error=None):
            nonlocal completed
            if not completed:
                completed = True
                self._emit(DispatchState(project=request.project, error=error, dispatched=error is None))

        try:
            self.adapter.request(request, complete)
        except Exception:
            complete("终端派发失败，请检查本机配置")
        return True


def _terminal_argv(config: dict, project: str, script: str, title: str) -> list[str]:
    """Internal Windows Terminal grammar shared by explicitly confirmed launchers."""
    paths = {}
    for key in ("terminal", "powershell"):
        value = config.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError(f"本机启动环境缺失：{key}")
        paths[key] = value
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    command = [paths["terminal"], "-w", "new", "new-tab", "--title", title,
               "--startingDirectory", project, paths["powershell"], "-NoLogo", "-NoProfile", "-NoExit",
               "-EncodedCommand", encoded]
    return [command[0], *(value.replace(";", "\\;") for value in command[1:])]


def terminal_command(config: dict, request: LaunchRequest) -> list[str]:
    """Paths are PowerShell literals inside UTF-16 encoding; no user shell fragments."""
    project = project_path(request.project)
    if request.tool not in ("codex", "claude") or request.mode not in ("new", "resume"):
        raise ValueError("未知终端启动请求")
    keys = (request.tool + "_cli",)
    paths = {}
    for key in keys:
        value = config.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError(f"本机启动环境缺失：{key}")
        paths[key] = value
    literal = lambda value: "'" + value.replace("'", "''") + "'"
    cli_args = {("codex", "new"): "", ("codex", "resume"): " resume --last",
                ("claude", "new"): "", ("claude", "resume"): " --continue"}
    script = ("Set-Location -LiteralPath " + literal(project) + "; "
              "& " + literal(paths[request.tool + "_cli"]) + cli_args[(request.tool, request.mode)])
    # Terminal splits even quoted arguments on semicolons before parsing its
    # subcommands. Escape that additional grammar, not just Windows argv.
    return _terminal_argv(config, project, script, "muti-ai · " + request.tool)


class WindowsTerminalAdapter(QObject):
    """Asynchronous Windows Terminal handoff. Child shells outlive the GUI."""
    def __init__(self, config, parent=None, *, command_builder=terminal_command):
        super().__init__(parent)
        self.config = config
        self.command_builder = command_builder
        self.process = None
        self.timer = QTimer(self)
        self.timer.setInterval(50)

    def request(self, request, complete):
        try:
            command = self.command_builder(self.config, request)
        except ValueError as error:
            complete(str(error))
            return
        if os.name != "nt":
            complete("真实终端启动仅支持 Windows")
            return
        # Popen does not kill children on destruction: both broker and terminal
        # survive GUI closure, including a handoff still in flight.
        try:
            self.process = subprocess.Popen(command, cwd=request.project, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        except OSError:
            complete("Windows Terminal 未能打开")
            return
        deadline = time.monotonic() + 10

        def poll():
            code = self.process.poll()
            if code is None and time.monotonic() < deadline:
                return
            self.timer.stop()
            self.timer.timeout.disconnect(poll)
            self.process = None
            error = ("终端派发状态未确认，请先检查已打开窗口" if code is None else
                     f"Windows Terminal 派发失败（退出码 {code}）" if code else None)
            complete(error)

        self.timer.timeout.connect(poll)
        self.timer.start()


class DemoTerminalAdapter(QObject):
    def __init__(self, parent=None, delay_ms=500):
        super().__init__(parent)
        self.delay_ms = delay_ms

    def request(self, request, complete):
        QTimer.singleShot(self.delay_ms, lambda: complete(None))
