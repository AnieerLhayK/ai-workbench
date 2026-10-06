import io
from types import SimpleNamespace
import pytest
from ai_workbench.storage import ProcessLock, atomic_json, read_json
from ai_workbench.windows import Identity, WindowsProcesses
from ai_workbench.worker import ToolWorker, commander_event


@pytest.mark.parametrize("proxy_name", ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"])
def test_commander_launch_enables_existing_environment_proxy(monkeypatch, proxy_name):
    import os
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NODE_USE_ENV_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(proxy_name, "http://127.0.0.1:9999")
    captured = {}
    monkeypatch.setattr("ai_workbench.windows.subprocess.Popen", lambda *args, **kwargs: captured.update(kwargs))
    WindowsProcesses({"npx": "/runtime/npx.cmd"}).launch("commander")
    assert captured.get("env", {}).get("NODE_USE_ENV_PROXY") == "1"
    assert (captured["env"].get(proxy_name) or captured["env"].get(proxy_name.upper())) == "http://127.0.0.1:9999"
    assert "NODE_USE_ENV_PROXY" not in os.environ


@pytest.mark.parametrize("explicit", ["0", "1"])
def test_commander_launch_preserves_explicit_proxy_mode(monkeypatch, explicit):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("NODE_USE_ENV_PROXY", explicit)
    captured = {}
    monkeypatch.setattr("ai_workbench.windows.subprocess.Popen", lambda *args, **kwargs: captured.update(kwargs))
    WindowsProcesses({"npx": "/runtime/npx.cmd"}).launch("commander")
    assert captured.get("env", {}).get("NODE_USE_ENV_PROXY") == explicit


def test_commander_launch_without_proxy_keeps_direct_network(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NODE_USE_ENV_PROXY"):
        monkeypatch.delenv(name, raising=False)
    captured = {}
    monkeypatch.setattr("ai_workbench.windows.subprocess.Popen", lambda *args, **kwargs: captured.update(kwargs))
    WindowsProcesses({"npx": "/runtime/npx.cmd"}).launch("commander")
    assert "NODE_USE_ENV_PROXY" not in captured.get("env", {})


def test_hermes_launch_does_not_enable_node_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.delenv("NODE_USE_ENV_PROXY", raising=False)
    captured = {}
    monkeypatch.setattr("ai_workbench.windows.subprocess.Popen", lambda *args, **kwargs: captured.update(kwargs))
    WindowsProcesses({"hermes_pythonw": "/runtime/Scripts/pythonw.exe", "hermes_home": "/profile"}).launch("hermes")
    assert "NODE_USE_ENV_PROXY" not in captured["env"]


class Backend:
    def __init__(self):
        self.target = None
        self.launches = 0
        self.stops = 0
        self.kills = []
        self.fail = None
        self.launcher = SimpleNamespace(pid=80, stdout=io.BytesIO(b""), poll=lambda: None)

    def discover(self, tool):
        if self.fail == "probe": raise RuntimeError("probe failed")
        return self.target

    def identity(self, pid):
        return Identity(pid, "created", "runtime", "command")

    def launch(self, tool):
        if self.fail == "start": raise RuntimeError("start failed")
        self.launches += 1
        self.launcher.stdout = io.BytesIO(b"")
        return self.launcher

    def stop(self, tool, identity):
        if self.fail == "stop": raise RuntimeError("stop failed")
        self.stops += 1
        self.target = None

    def kill_exact(self, identity):
        self.kills.append(identity)


def setup(tmp_path, tool="commander"):
    backend = Backend()
    clock = [0.0]
    config = {"data_root": str(tmp_path), "hermes_home": str(tmp_path / "hermes")}
    worker = ToolWorker(tool, config, backend, lambda: clock[0])
    worker.probe()
    return worker, backend, clock


def test_start_needs_runtime_ready_stop_and_reentry(tmp_path):
    worker, backend, _ = setup(tmp_path)
    worker.request({"id": "start", "running": True})
    worker.request({"id": "duplicate", "running": True})
    worker.probe()
    assert backend.launches == 1 and worker.state["phase"] == "starting"
    backend.target = backend.identity(90)
    worker.probe()
    assert worker.state["phase"] == "starting"
    worker.events.put("ready")
    worker.probe()
    assert worker.state["phase"] == "running"
    worker.request({"id": "stop", "running": False})
    worker.probe()
    assert backend.stops == 1 and not worker.state["running"]


def test_start_and_stop_failure_preserve_actual_state(tmp_path):
    worker, backend, _ = setup(tmp_path)
    backend.fail = "start"
    worker.request({"id": "a", "running": True})
    worker.probe()
    assert worker.state["phase"] == "failed" and not worker.state["running"]
    backend.target = backend.identity(90)
    backend.fail = "stop"
    worker.request({"id": "b", "running": False})
    worker.probe()
    assert worker.state["phase"] == "failed" and worker.state["running"]


def test_commander_exit_preserves_safe_authorization_cause(tmp_path):
    worker, backend, _ = setup(tmp_path)
    worker.request({"id": "auth-failure", "running": True})
    worker._output(io.BytesIO(b"Error: Authorization timeout - user did not authorize within the time limit\n"))
    backend.launcher.poll = lambda: 1
    worker.probe()
    assert worker.state["phase"] == "failed" and not worker.state["running"]
    assert "授权超时" in worker.state["error"]
    assert worker.state["error"] != "启动进程提前退出"


@pytest.mark.parametrize(("line", "expected"), [
    ("Device startup failed: Authorization failed: access_denied", "fatal:auth_denied"),
    ("Device startup failed: Authorization failed: expired_token", "fatal:auth_expired"),
    ("Device startup failed: Device code has expired", "fatal:auth_expired"),
    ("Device startup failed: Device flow expired", "fatal:auth_expired"),
    ("Device startup failed: Invalid verification code", "fatal:auth_invalid"),
    ("Device startup failed: fetch failed", "fatal:network"),
    ("Device startup failed: unexpected token=PRIVATE user@example.com ABCD-1234", "fatal:provider"),
])
def test_startup_error_is_normalized_without_raw_data(line, expected):
    assert commander_event(line) == expected


def test_unknown_exit_keeps_numeric_code(tmp_path):
    worker, backend, _ = setup(tmp_path)
    worker.request({"id": "exit", "running": True})
    backend.launcher.poll = lambda: 42
    worker.probe()
    assert worker.state["exit_code"] == 42
    assert "42" in worker.state["error"]


def test_failed_reauthentication_does_not_persist_accounts(tmp_path):
    worker, backend, _ = setup(tmp_path)
    worker.request({"id": "fail", "running": True})
    worker._output(io.BytesIO(b"Device startup failed: unexpected token=PRIVATE user@example.com ABCD-1234\n"))
    backend.launcher.poll = lambda: 1
    worker.probe()
    contents = (worker.root / "events.log").read_text(encoding="utf-8") + (worker.root / "state.json").read_text(encoding="utf-8")
    assert worker.state["failure_code"] == "provider"
    assert all(private not in contents for private in ("PRIVATE", "user@example.com", "ABCD-1234"))


def test_final_stderr_is_consumed_before_exit_result(tmp_path):
    worker, backend, _ = setup(tmp_path)
    worker.request({"id": "race", "running": True})
    def poll():
        worker.events.put("fatal:auth_denied")
        return 1
    backend.launcher.poll = poll
    worker.probe()
    assert worker.state["failure_code"] == "auth_denied"
    assert "被拒绝" in worker.state["error"]


def test_delayed_reader_keeps_failed_start_pending(tmp_path):
    worker, backend, clock = setup(tmp_path)
    worker._output = lambda *args: args[0].close()
    worker.request({"id": "slow-output", "running": True})
    worker.output_complete.clear()
    backend.launcher.poll = lambda: 1
    worker.probe()
    assert worker.operation and worker.state["phase"] == "starting"
    clock[0] = 0.5
    worker.events.put("fatal:auth_expired")
    worker.output_complete.set()
    worker.probe()
    assert worker.operation is None
    assert worker.state["failure_code"] == "auth_expired"


def test_output_drain_has_explicit_bounded_fallback(tmp_path):
    worker, backend, clock = setup(tmp_path)
    worker._output = lambda *args: args[0].close()
    worker.request({"id": "stuck-output", "running": True})
    worker.output_complete.clear()
    backend.launcher.poll = lambda: 1
    worker.probe()
    clock[0] = 3.1
    worker.probe()
    assert worker.operation is None
    assert "读取超时" in worker.state["error"]


def test_previous_reader_cannot_fail_a_new_start(tmp_path):
    worker, backend, _ = setup(tmp_path)
    worker.request({"id": "first", "running": True})
    previous = worker.output_generation
    worker.output_complete.set()
    backend.launcher.poll = lambda: 1
    worker.probe()
    backend.launcher.poll = lambda: None
    worker.request({"id": "retry", "running": True})
    worker.events.put((previous, "fatal:auth_expired"))
    backend.target = backend.identity(90)
    worker.events.put((worker.output_generation, "ready"))
    worker.probe()
    assert worker.state["phase"] == "running"
    assert worker.startup_failure is None and worker.state["failure_code"] is None


def test_failure_enqueued_at_eof_is_consumed(tmp_path):
    worker, backend, _ = setup(tmp_path)
    worker.request({"id": "eof-race", "running": True})
    backend.launcher.poll = lambda: 1
    def completed():
        worker.events.put("fatal:auth_expired")
        return True
    worker.output_complete = SimpleNamespace(is_set=completed)
    worker.probe()
    assert worker.state["failure_code"] == "auth_expired"


def test_timeout_cancels_only_owned_launcher(tmp_path):
    worker, backend, clock = setup(tmp_path)
    worker.request({"id": "a", "running": True})
    clock[0] = 121
    worker.probe()
    assert worker.state["phase"] == "failed"
    assert backend.kills == [backend.identity(80)]


def test_auth_extends_deadline_and_output_is_whitelisted(tmp_path):
    worker, backend, clock = setup(tmp_path)
    worker.request({"id": "a", "running": True})
    worker.events.put("authorization")
    clock[0] = 121
    worker.probe()
    assert worker.state["phase"] == "starting" and not backend.kills
    assert commander_event("secret email token authorization code ABCD-1234") is None
    assert commander_event("✅ Device ready:") == "ready"
    assert "ABCD" not in (worker.root / "events.log").read_text()


def test_crash_disconnect_recovery_and_adoption(tmp_path):
    worker, backend, _ = setup(tmp_path)
    backend.target = backend.identity(90)
    worker.probe()
    assert worker.state["running"] and backend.launches == 0
    assert "未确认" in worker.state["detail"]
    worker.events.put("ready")
    worker.probe()
    worker.events.put("disconnected")
    worker.probe()
    assert worker.state["running"] and "异常" in worker.state["detail"]
    worker.events.put("reconnected")
    worker.probe()
    assert worker.state["detail"] == "运行中"
    backend.target = None
    worker.probe()
    assert not worker.state["running"] and worker.state["error"] == "进程意外退出"


def test_tool_isolation_and_hermes_runtime_ready(tmp_path):
    one, b1, _ = setup(tmp_path / "one")
    two, b2, _ = setup(tmp_path / "two", "hermes")
    one.request({"id": "a", "running": True})
    two.request({"id": "b", "running": True})
    b2.target = b2.identity(90)
    atomic_json(tmp_path / "two" / "hermes" / "gateway_state.json", {"pid": 90, "gateway_state": "running", "platforms": {}})
    two.probe()
    assert two.state["phase"] == "running" and one.state["phase"] == "starting"


def test_probe_failure_is_unknown(tmp_path):
    worker, backend, _ = setup(tmp_path)
    backend.fail = "probe"
    worker.probe()
    assert worker.state["phase"] == "unknown"


def test_hermes_restart_requires_new_runtime_evidence(tmp_path):
    worker, backend, _ = setup(tmp_path, "hermes")
    backend.target = backend.identity(90)
    atomic_json(tmp_path / "hermes" / "gateway_state.json", {"pid": 90, "gateway_state": "running"})
    worker.probe()
    worker.request({"id": "stop", "running": False})
    worker.probe()
    worker.request({"id": "restart", "running": True})
    backend.target = backend.identity(91)
    worker.probe()
    assert worker.state["phase"] == "starting"
    assert worker.connection == "unknown"


def test_replacement_invalidates_commander_health(tmp_path):
    worker, backend, _ = setup(tmp_path)
    backend.target = backend.identity(90)
    worker.probe()
    worker.events.put("ready")
    worker.probe()
    backend.target = Identity(90, "replacement", "runtime", "command")
    worker.probe()
    assert worker.state["running"] and "未确认" in worker.state["detail"]


def test_hermes_requires_profile_record_and_runtime(tmp_path):
    runtime = tmp_path / "venv" / "Scripts" / "pythonw.exe"
    backend = WindowsProcesses({"hermes_pythonw": str(runtime), "hermes_home": str(tmp_path / "profile")})
    identity = Identity(90, "created", str(runtime), "pythonw -m hermes_cli.main gateway run")
    assert not backend.matches("hermes", identity)
    atomic_json(tmp_path / "profile" / "gateway.pid", {"pid": 90, "kind": "hermes-gateway"})
    assert backend.matches("hermes", identity)
    wrong = Identity(90, "created", str(tmp_path / "unrelated.exe"), identity.command)
    assert not backend.matches("hermes", wrong)


def test_pid_reuse_prevents_termination(monkeypatch):
    backend = WindowsProcesses({})
    old = Identity(4, "old", "exe", "command")
    monkeypatch.setattr(backend, "identity", lambda pid: Identity(4, "new", "exe", "command"))
    with pytest.raises(RuntimeError, match="身份已变化"):
        backend.kill_exact(old)


def test_multiple_matching_processes_rejected(monkeypatch):
    backend = WindowsProcesses({"node": "node.exe"})
    rows = [Identity(pid, "created", "node.exe", 'node.exe "cache/@wonderwhy-er/desktop-commander/dist/index.js" remote') for pid in (4, 5)]
    monkeypatch.setattr(backend, "_query", lambda command: rows)
    with pytest.raises(RuntimeError, match="多个"):
        backend.discover("commander")


def test_lock_excludes_second_worker_and_atomic_state(tmp_path):
    first = ProcessLock(tmp_path / "worker.lock")
    second = ProcessLock(tmp_path / "worker.lock")
    assert first.acquired and not second.acquired
    first.close()
    third = ProcessLock(tmp_path / "worker.lock")
    assert third.acquired
    third.close()
    atomic_json(tmp_path / "state.json", {"running": True})
    assert read_json(tmp_path / "state.json")["running"]


def test_atomic_state_retries_windows_reader_lock(tmp_path, monkeypatch):
    import ai_workbench.storage as storage
    original = storage.os.replace
    attempts = []
    def replace(source, destination):
        attempts.append(source)
        if len(attempts) == 1:
            raise PermissionError("reader holds destination")
        original(source, destination)
    monkeypatch.setattr(storage.os, "replace", replace)
    atomic_json(tmp_path / "state.json", {"running": False})
    assert len(attempts) == 2
    assert read_json(tmp_path / "state.json") == {"running": False}
