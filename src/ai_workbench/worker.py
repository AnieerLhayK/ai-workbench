"""Detached per-tool control Module: no GUI lifetime or credential dependency."""
import os
import queue
import threading
import time
from pathlib import Path

from .storage import ProcessLock, atomic_json, read_json
from .windows import WindowsProcesses


STARTUP_FAILURES = {
    "auth_timeout": "设备授权超时。请重新开启，并在新打开的浏览器页面完成验证。",
    "auth_expired": "设备验证码已过期。请重新开启，并使用本次的新验证页面。",
    "auth_denied": "设备授权被拒绝。请检查浏览器设备验证页面的结果。",
    "auth_invalid": "设备验证码无效。请重新开启，并使用本次的新验证页面。",
    "auth_failed": "设备授权失败。请检查浏览器设备验证页面的结果。",
    "network": "Commander 网络请求失败。请检查网络或代理连接后重试。",
    "npm": "Commander 安装或更新失败。请检查 npm 网络及缓存权限。",
    "runtime": "Commander 本机运行环境出错。请检查 Node 和模块加载。",
    "provider": "Commander 启动失败，上游错误暂未识别。",
}


def commander_event(line: str) -> str | None:
    """Whitelist status events; never persist raw CLI output or auth codes."""
    lowered = line.lower()
    if "device startup failed:" in lowered or lowered.lstrip().startswith(("error:", "npm error", "npm err!")):
        failures = (
            ("auth_timeout", ("authorization timeout",)),
            ("auth_expired", ("expired_token", "code expired", "expired code", "code has expired", "device flow expired")),
            ("auth_denied", ("access_denied", "authorization denied")),
            ("auth_invalid", ("invalid verification code", "invalid user code", "invalid_grant")),
            ("network", ("fetch failed", "enotfound", "econnrefused", "econnreset", "etimedout", "network error", "certificate")),
            ("runtime", ("cannot find module", "err_module_not_found", "enoent")),
            ("auth_failed", ("authorization failed", "authentication failed")),
        )
        for kind, markers in failures:
            if any(marker in lowered for marker in markers):
                return "fatal:" + kind
        return "fatal:npm" if lowered.lstrip().startswith(("npm error", "npm err!")) else "fatal:provider"
    if "Device ready:" in line:
        return "ready"
    if "Channel subscribed" in line:
        return "reconnected"
    if any(word in line for word in ("Channel closed", "Channel error", "subscription timed out", "NOT reachable", "device is now offline", "session expired", "local MCP server disconnected")):
        return "disconnected"
    if "Authenticating with Remote MCP" in line or "Please complete authentication" in line:
        return "authorization"
    return None


class ToolWorker:
    def __init__(self, tool: str, config: dict, backend=None, clock=time.monotonic):
        self.tool, self.config = tool, config
        self.root = Path(config["data_root"]) / "runtime" / tool
        self.backend = backend or WindowsProcesses(config)
        self.clock = clock
        self.operation = None
        self.target = None
        self.launcher = None
        self.launch_identity = None
        self.events = queue.Queue()
        self.write_lock = threading.Lock()
        self.connection = "unknown"
        self.initialized = False
        self.previous_running = False
        self.startup_failure = None
        self.output_generation = 0
        self.output_complete = threading.Event()
        prior = read_json(self.root / "state.json")
        self.interrupted = prior.get("active_request")
        self.state = {"phase": "checking", "running": False, "error": None, "detail": "正在检查…", "completed_request": None, "active_request": None, "failure_code": None, "exit_code": None}

    def _output(self, stream, generation=None, complete=None):
        generation = self.output_generation if generation is None else generation
        complete = self.output_complete if complete is None else complete
        try:
            for raw in iter(stream.readline, b""):
                event = commander_event(raw.decode("utf-8", errors="replace"))
                if event:
                    self.events.put((generation, event))
        finally:
            stream.close()
            complete.set()

    def request(self, request: dict):
        if self.operation:
            return  # The UI rejects reentry; concurrent requests stay queued.
        try:
            identity = self.backend.discover(self.tool)
            running = identity is not None
            wanted = request["running"]
            if not isinstance(wanted, bool) or not isinstance(request.get("id"), str):
                return
            if wanted == running:
                self._finish(request["id"], running, None)
                return
            self.operation = {"id": request["id"], "running": wanted, "started": self.clock(), "timeout": 120 if wanted else 30}
            self.state.update(phase="starting" if wanted else "stopping", running=running, error=None, detail="正在启动…" if wanted else "正在停止…", active_request=request["id"])
            if wanted:
                self.startup_failure = None
                self.state.update(failure_code=None, exit_code=None)
                self.output_generation += 1
                self.output_complete = threading.Event()
                self.connection = "unknown"
                self.initialized = False
                self.launcher = self.backend.launch(self.tool)
                self.launch_identity = self.backend.identity(self.launcher.pid)
                if self.tool == "commander":
                    threading.Thread(target=self._output, args=(self.launcher.stdout, self.output_generation, self.output_complete), daemon=True).start()
            else:
                self.target = identity
                self.backend.stop(self.tool, identity)
        except Exception as error:
            self._finish(request.get("id"), self.state["running"], str(error))

    def _finish(self, request_id, running: bool, error: str | None):
        self.state.update(phase="failed" if error else ("running" if running else "stopped"), running=running, error=error, detail=self._detail(running), completed_request=request_id, active_request=None)
        self.operation = None
        self.previous_running = running

    def _detail(self, running: bool) -> str:
        if not running:
            return "已停止"
        if self.connection == "ready":
            return "运行中"
        if self.connection == "disconnected":
            return "运行中 · 连接异常"
        if self.connection == "authorization":
            return "等待浏览器授权"
        return "运行中 · 连接状态未确认"

    def _consume_events(self):
        while not self.events.empty():
            event = self.events.get_nowait()
            if isinstance(event, tuple):
                generation, event = event
                if generation != self.output_generation:
                    continue
            if event.startswith("fatal:"):
                code = event.partition(":")[2]
                if code in STARTUP_FAILURES:
                    self.startup_failure = code
            elif event == "ready":
                self.initialized = True
                self.connection = "ready"
            elif event == "reconnected":
                if self.initialized:
                    self.connection = "ready"
            else:
                self.connection = event
            if event == "authorization" and self.operation:
                self.operation["timeout"] = 600
            # Only the normalized event is stored, never CLI text.
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / "events.log").open("a", encoding="utf-8") as stream:
                stream.write(f"{int(time.time())} {event}\n")

    def probe(self):
        try:
            identity = self.backend.discover(self.tool)
        except Exception:
            self.state.update(phase="unknown", error="无法确认进程身份或状态", detail="状态未确认")
            self._write_state()
            return
        if identity != self.target and not self.operation:
            self.connection = "unknown"
            self.initialized = False
            while not self.events.empty():
                self.events.get_nowait()
        self._consume_events()
        try:
            running = identity is not None
            if self.interrupted:
                self._finish(self.interrupted, running, "控制程序曾中断，已重新核对进程状态")
                self.interrupted = None
            if self.tool == "hermes" and identity:
                self.connection = "unknown"
                runtime = read_json(Path(self.config["hermes_home"]) / "gateway_state.json")
                if runtime.get("pid") == identity.pid:
                    phase = runtime.get("gateway_state")
                    platforms = runtime.get("platforms", {}).values()
                    self.connection = "disconnected" if any(p.get("state") in ("disconnected", "error", "failed") for p in platforms if isinstance(p, dict)) else ("ready" if phase == "running" else "unknown")
                    if phase == "startup_failed" and self.operation:
                        self._finish(self.operation["id"], running, "Hermes 启动失败，请检查其本机配置")
            if self.operation:
                operation = self.operation
                if not operation["running"] and not running:
                    self._finish(operation["id"], False, None)
                elif operation["running"] and running and (self.tool == "hermes" and self.connection == "ready" or self.tool == "commander" and self.initialized):
                    self._finish(operation["id"], True, None)
                elif operation["running"] and self.launcher and self.launcher.poll() is not None and not running:
                    incomplete = False
                    if self.tool == "commander":
                        if not self.output_complete.is_set():
                            drain_started = operation.setdefault("drain_started", self.clock())
                            drain_deadline = min(drain_started + 3, operation["started"] + operation["timeout"])
                            if self.clock() < drain_deadline:
                                self.state.update(phase="starting", running=False, error=None, detail="启动进程已退出，正在读取退出原因…")
                                self.target = identity
                                self.previous_running = False
                                self._write_state()
                                return
                            incomplete = True
                        # The reader enqueues its final event before signaling EOF.
                        # Consume after observing that signal, not before it.
                        self._consume_events()
                    code = self.launcher.poll()
                    failure = self.startup_failure
                    self.state.update(exit_code=code, failure_code=failure or "unknown_exit")
                    message = STARTUP_FAILURES.get(failure, "启动进程提前退出，未确认原因")
                    if incomplete:
                        message += "；退出原因读取超时"
                    self._finish(operation["id"], False, f"{message}（退出码 {code}）")
                elif self.clock() - operation["started"] >= operation["timeout"]:
                    if not running and operation["running"] and self.launch_identity:
                        self.backend.kill_exact(self.launch_identity)
                    self._finish(operation["id"], running, "操作超时；请核对当前状态后重试")
                else:
                    self.state["running"] = running
                    if self.connection == "authorization":
                        self.state["detail"] = "等待浏览器授权"
            else:
                if self.previous_running and not running and self.state["phase"] != "failed":
                    self.state.update(phase="failed", error="进程意外退出")
                elif self.state["phase"] not in ("failed",):
                    self.state.update(phase="running" if running else "stopped", error=None)
                self.state.update(running=running, detail=self._detail(running))
            self.target = identity
            self.previous_running = running
        except Exception:
            self.state.update(phase="unknown", error="无法确认进程身份或状态", detail="状态未确认")
        self._write_state()

    def _write_state(self):
        with self.write_lock:
            self.state.update(updated_at=time.time(), worker_pid=os.getpid(), pid=self.target.pid if self.target else None)
            atomic_json(self.root / "state.json", dict(self.state))

    def run(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = ProcessLock(self.root / "worker.lock")
        if not lock.acquired:
            return
        finished = threading.Event()
        def heartbeat():
            while not finished.wait(1):
                self._write_state()
        threading.Thread(target=heartbeat, daemon=True).start()
        try:
            next_probe = 0
            while True:
                if self.clock() >= next_probe:
                    self.probe()
                    next_probe = self.clock() + 2
                if not self.operation:
                    for path in sorted((self.root / "requests").glob("*.json")):
                        request = read_json(path)
                        path.unlink()
                        self.request(request)
                        self.probe()
                        break
                time.sleep(0.2)
        finally:
            finished.set()
            lock.close()


if __name__ == "__main__":
    import argparse
    from .storage import load_config
    parser = argparse.ArgumentParser(description="Detached local tool controller")
    parser.add_argument("tool", choices=("commander", "hermes"))
    parser.add_argument("--config", type=Path, required=True)
    arguments = parser.parse_args()
    ToolWorker(arguments.tool, load_config(arguments.config)).run()
