import base64
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from ai_workbench.app import Workbench
from ai_workbench.terminal import (DispatchState, LaunchRequest, TerminalLauncher,
                                  DemoTerminalAdapter, WindowsTerminalAdapter,
                                  project_path, recent_projects, remember_project, terminal_command)
from ai_workbench.storage import read_json


class ControlledTerminalAdapter:
    def __init__(self):
        self.requests = []

    def request(self, request, complete):
        self.requests.append((request, complete))

    def complete(self, error=None):
        self.requests[-1][1](error)


def configured(tmp_path):
    result = {}
    for key in ("terminal", "powershell", "codex_cli", "claude_cli"):
        path = tmp_path / (key + ".cmd")
        path.touch()
        result[key] = str(path)
    return result


@pytest.mark.parametrize("tool,mode,suffix", [
    ("codex", "new", ""), ("codex", "resume", " resume --last"),
    ("claude", "new", ""), ("claude", "resume", " --continue"),
])
def test_literal_paths_and_exact_commands(tmp_path, tool, mode, suffix):
    project = tmp_path / "中文 space ' ; $(anything) & project"
    project.mkdir()
    config = configured(tmp_path)
    cli = tmp_path / "cli ' & name.cmd"
    cli.touch()
    config[tool + "_cli"] = str(cli)
    command = terminal_command(config, LaunchRequest(tool, str(project), mode))
    script = base64.b64decode(command[-1]).decode("utf-16-le")
    literal = lambda value: "'" + value.replace("'", "''") + "'"
    assert script == "Set-Location -LiteralPath " + literal(str(project.resolve())) + "; & " + literal(str(cli)) + suffix
    assert command[:4] == [config["terminal"], "-w", "new", "new-tab"]
    assert command[command.index("--startingDirectory") + 1] == str(project.resolve()).replace(";", "\\;")
    assert "--all" not in script and "dangerously" not in script
    assert "-NoExit" in command


def test_terminal_parser_does_not_split_special_paths(tmp_path):
    import re
    project = tmp_path / "project;split-pane"
    project.mkdir()
    config = configured(tmp_path)
    shell = tmp_path / "shell;new-tab.exe"
    shell.touch()
    config["powershell"] = str(shell)
    command = terminal_command(config, LaunchRequest("codex", str(project), "new"))
    # Microsoft's BuildCommands searches every argv with this delimiter rule,
    # then Commandline::AddArg removes the backslash before literal semicolons.
    assert not any(re.search(r"(?<!\\);", value) for value in command[1:])
    restored = [value.replace("\\;", ";") for value in command[1:]]
    assert str(project.resolve()) in restored and str(shell) in restored


@pytest.mark.parametrize("key", ["terminal", "powershell", "codex_cli", "claude_cli"])
def test_missing_optional_environment_only_fails_requested_tool(tmp_path, key):
    config = configured(tmp_path)
    del config[key]
    tool = "claude" if key == "claude_cli" else "codex"
    with pytest.raises(ValueError, match=key):
        terminal_command(config, LaunchRequest(tool, str(tmp_path), "new"))
    if key.endswith("_cli"):
        other = "claude" if tool == "codex" else "codex"
        assert terminal_command(config, LaunchRequest(other, str(tmp_path), "new"))


def test_dispatch_snapshot_delay_reentry_error_retry_independence(tmp_path):
    first, second = ControlledTerminalAdapter(), ControlledTerminalAdapter()
    codex, claude = TerminalLauncher(first), TerminalLauncher(second)
    observed = []
    codex.observe(observed.append)
    assert codex.launch("codex", str(tmp_path), "resume")
    assert codex.state.pending
    assert not codex.launch("codex", str(tmp_path), "new")
    assert claude.launch("claude", str(tmp_path), "new")
    assert first.requests[0][0] == LaunchRequest("codex", str(tmp_path.resolve()), "resume")
    first.complete("未能打开")
    assert codex.state.error and not codex.state.dispatched
    assert claude.state.pending
    assert codex.launch("codex", str(tmp_path), "new")
    first.complete()
    assert codex.state.dispatched and not codex.state.pending
    second.complete()
    assert claude.state.dispatched
    assert len(first.requests) == 2


@pytest.mark.parametrize("tool,project,mode", [("unknown", "valid", "new"), ("codex", "valid", "unknown"), ("codex", "missing", "new"), ("claude", "relative", "resume")])
def test_invalid_requests_never_dispatch(tmp_path, tool, project, mode):
    adapter = ControlledTerminalAdapter()
    launcher = TerminalLauncher(adapter)
    directory = str(tmp_path) if project == "valid" else str(tmp_path / "absent") if project == "missing" else "relative"
    assert not launcher.launch(tool, directory, mode)
    assert launcher.state.error and not adapter.requests


def test_adapter_exception_is_safe_and_retryable(tmp_path):
    class Broken:
        def request(self, request, complete):
            raise RuntimeError("private raw details")
    launcher = TerminalLauncher(Broken())
    assert launcher.launch("codex", str(tmp_path), "new")
    assert "private" not in launcher.state.error
    assert not launcher.state.pending


def test_duplicate_late_completion_cannot_finish_new_dispatch(tmp_path):
    adapter = ControlledTerminalAdapter()
    launcher = TerminalLauncher(adapter)
    launcher.launch("codex", str(tmp_path), "new")
    previous_complete = adapter.requests[-1][1]
    adapter.complete()
    launcher.launch("codex", str(tmp_path), "resume")
    previous_complete("late stale error")
    assert launcher.state.pending and not launcher.state.error
    adapter.complete()
    assert launcher.state.dispatched


def test_windows_spawn_failure_and_timeout(qt_app, tmp_path, monkeypatch):
    config = configured(tmp_path)
    launcher = TerminalLauncher(WindowsTerminalAdapter(config))
    def fail(*args, **kwargs): raise OSError("private details")
    monkeypatch.setattr("ai_workbench.terminal.subprocess.Popen", fail)
    launcher.launch("codex", str(tmp_path), "new")
    assert "未能打开" in launcher.state.error and "private" not in launcher.state.error
    class Pending:
        def poll(self): return None
    monkeypatch.setattr("ai_workbench.terminal.subprocess.Popen", lambda *args, **kwargs: Pending())
    clock = iter([0, 20])
    monkeypatch.setattr("ai_workbench.terminal.time.monotonic", lambda: next(clock))
    launcher.launch("claude", str(tmp_path), "new")
    QTest.qWait(100)
    assert "状态未确认" in launcher.state.error and not launcher.state.pending


def test_recent_project_limit_dedup_corrupt_and_missing(tmp_path):
    paths = [str(tmp_path / str(index)) for index in range(14)]
    assert recent_projects([None, "relative", paths[0], paths[0], *paths[1:]]) == paths[:10]
    assert remember_project(paths[5], paths) == [paths[5], *paths[:5], *paths[6:10]]
    assert recent_projects(None) == []
    with pytest.raises(ValueError): project_path(paths[0])


def test_qt_project_buttons_pending_theme_hidden_close_and_preferences(qt_app, tmp_path):
    adapters = {key: ControlledTerminalAdapter() for key in ("codex", "claude")}
    launchers = {key: TerminalLauncher(adapter) for key, adapter in adapters.items()}
    preferences = tmp_path / "preferences.json"
    preferences.write_text('{"theme":"dark","other":42}', encoding="utf-8")
    window = Workbench(preferences=preferences, demo=True, terminal_launchers=launchers)
    window.show()
    try:
        assert all(not button.isEnabled() for row in window.terminal_rows.values() for button in row.buttons.values())
        window.select_project(str(tmp_path))
        window.groups["codex"].header.click()
        window.groups["claude"].header.click()
        row = window.terminal_rows["codex"]
        window.scroll.ensureWidgetVisible(row.buttons["resume"])
        row.buttons["resume"].setFocus()
        QTest.keyClick(row.buttons["resume"], Qt.Key.Key_Space)
        assert launchers["codex"].state.pending
        assert all(not button.isEnabled() for button in row.buttons.values())
        assert window.terminal_rows["claude"].buttons["new"].isEnabled()
        window.groups["codex"].header.click()
        assert window.groups["codex"].mark.timer.isActive()
        next_project = tmp_path / "next"
        next_project.mkdir()
        window.select_project(str(next_project))
        window.set_theme("light")
        assert len(adapters["codex"].requests) == 1 and not adapters["claude"].requests
        assert adapters["codex"].requests[0][0].project == str(tmp_path.resolve())
        adapters["codex"].complete("派发失败")
        assert "有错误" in window.groups["codex"].summary.text()
        window.groups["codex"].header.click()
        assert row.error.text() == "派发失败" and row.buttons["new"].isEnabled()
        row.buttons["new"].click()
        window.close()
        adapters["codex"].complete()
        assert launchers["codex"].state.dispatched
        assert len(adapters["codex"].requests) == 2
        reopened = Workbench(preferences=preferences, demo=True)
        assert reopened.project == str(next_project) and reopened.theme == "light"
        assert read_json(preferences)["other"] == 42
        assert reopened.recent_projects == [str(next_project), str(tmp_path)]
        reopened.close()
    finally:
        window.close()


def test_missing_saved_project_does_not_fall_back(qt_app, tmp_path):
    preferences = tmp_path / "preferences.json"
    preferences.write_text('{"selected_project":"' + str(tmp_path / "missing").replace('\\', '\\\\') + '","recent_projects":null}', encoding="utf-8")
    window = Workbench(demo=True, preferences=preferences)
    assert "不存在" in window.project_hint.text()
    assert all(not button.isEnabled() for row in window.terminal_rows.values() for button in row.buttons.values())
    window.close()


def test_demo_dispatch_never_opens_process(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr("ai_workbench.terminal.subprocess.Popen", lambda *args, **kwargs: pytest.fail("real process in demo"))
    launcher = TerminalLauncher(DemoTerminalAdapter(delay_ms=20))
    launcher.launch("claude", str(tmp_path), "new")
    QTest.qWait(150)
    assert launcher.state.dispatched


@pytest.mark.parametrize("code,error", [(0, False), (7, True)])
def test_windows_handoff_result(qt_app, tmp_path, monkeypatch, code, error):
    class Broker:
        def poll(self): return code
    monkeypatch.setattr("ai_workbench.terminal.os.name", "nt")
    monkeypatch.setattr("ai_workbench.terminal.subprocess.CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr("ai_workbench.terminal.subprocess.CREATE_NEW_PROCESS_GROUP", 0, raising=False)
    monkeypatch.setattr("ai_workbench.terminal.subprocess.Popen", lambda *args, **kwargs: Broker())
    launcher = TerminalLauncher(WindowsTerminalAdapter(configured(tmp_path)))
    launcher.launch("codex", str(tmp_path), "new")
    QTest.qWait(100)
    assert bool(launcher.state.error) == error
    assert launcher.state.dispatched != error
