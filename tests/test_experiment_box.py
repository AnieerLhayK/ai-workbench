import base64
from copy import deepcopy
import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from ai_workbench.experiment_box.model import TrialStore, StoreError, demo_store
from ai_workbench.experiment_box.launch import CommandRequest, ExperimentLauncher, command_request, command_argv
from ai_workbench.experiment_box.dialogs import TrialDialog, ResultDialog, ConfirmDialog
from ai_workbench.experiment_box.window import ExperimentWindow
from ai_workbench.experiment_box.app import load_config
from ai_workbench.terminal import WindowsTerminalAdapter


def fields(**changes):
    return dict(name="本地试验", source="", goal="检查输出", directory="", command="", next_action="准备目录",
                status="待开始", tags=["本地", "本地"]) | changes


class ControlledAdapter:
    def __init__(self):
        self.requests = []

    def request(self, request, complete):
        self.requests.append((request, complete))


def test_storage_roundtrip_search_edit_record_and_selection(tmp_path):
    path = tmp_path / "trials.json"
    store = TrialStore(path)
    assert store.trials() == [] and not path.exists()
    first = store.save(fields())
    second = store.save(fields(name="Pi", tags=["AI"], status="暂停"))
    assert store.trials("ai")[0]["id"] == second
    assert store.trials(status="暂停")[0]["id"] == second
    assert store.trials("missing") == []
    assert store.trials()[0]["tags"] == ["本地"]
    store.save(fields(name="更新"), first)
    reference = str(tmp_path / "missing-file.txt")
    store.record(first, "输出正确", "重复验证", [reference])
    store.select(second)
    restored = TrialStore(path)
    assert restored.snapshot() == store.snapshot()
    assert restored.snapshot()["selected_id"] == second
    trial = restored.trials("更新")[0]
    assert trial["status"] == "待开始"
    assert trial["next_action"] == "重复验证"
    assert trial["records"][0]["paths"] == [reference]
    copy = restored.snapshot()
    copy["trials"].clear()
    assert len(restored.trials()) == 2


@pytest.mark.parametrize("text", ["not json", "{}", '{"version":2,"trials":[]}', '{"version":1,"selected_id":"lost","trials":[]}'])
def test_corrupt_store_preserves_original(tmp_path, text):
    path = tmp_path / "trials.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(StoreError, match="原文件已保留"):
        TrialStore(path)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("mutate", [
    lambda value: value["trials"][0].update(records=[{}]),
    lambda value: value["trials"][0].update(status="unknown"),
    lambda value: value["trials"].append(deepcopy(value["trials"][0])),
    lambda value: value["trials"][0].update(created_at="not time"),
])
def test_invalid_structure_fails_closed(tmp_path, mutate):
    store = TrialStore(None)
    store.save(fields())
    value = store.snapshot()
    mutate(value)
    path = tmp_path / "trials.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(StoreError):
        TrialStore(path)


def test_writer_failure_preserves_memory_and_file(tmp_path):
    path = tmp_path / "trials.json"
    store = TrialStore(path)
    store.save(fields())
    before = store.snapshot(), path.read_bytes()
    def denied(*args):
        raise PermissionError("denied")
    store.writer = denied
    with pytest.raises(StoreError, match="保存失败"):
        store.save(fields(name="not saved"))
    assert (store.snapshot(), path.read_bytes()) == before


@pytest.mark.parametrize("source", ["file:///private/secret", "javascript:alert(1)", "https://", "https://[invalid"])
def test_only_web_source_links(source):
    with pytest.raises(StoreError, match="HTTP"):
        TrialStore(None).save(fields(source=source))


def configured(tmp_path):
    config = {}
    for key in ("terminal", "powershell"):
        file = tmp_path / (key + ".exe")
        file.touch()
        config[key] = str(file)
    return config


def test_command_encoding_isolated_from_path_syntax(tmp_path):
    directory = tmp_path / "中文 space ' ; $(name)"
    directory.mkdir()
    script = "Write-Output '中文'; Write-Output \"quote\"\nWrite-Output '$literal'"
    request = command_request(fields(directory=str(directory), command=script))
    argv = command_argv(configured(tmp_path), request)
    decoded = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert "Set-Location -LiteralPath '" + str(directory.resolve()).replace("'", "''") + "' -ErrorAction Stop" in decoded
    encoded_user = decoded.split("FromBase64String('")[1].split("')")[0]
    assert base64.b64decode(encoded_user).decode("utf-8") == script
    assert "-NoExit" in argv and argv[:4] == [configured(tmp_path)["terminal"], "-w", "new", "new-tab"]
    assert argv[argv.index("--startingDirectory") + 1] == str(directory.resolve()).replace(";", "\\;")


@pytest.mark.parametrize("directory,command", [("", "echo x"), ("missing", "echo x"), ("valid", ""), ("valid", "\x00")])
def test_launch_validation(tmp_path, directory, command):
    with pytest.raises(ValueError):
        command_request(fields(directory=str(tmp_path) if directory == "valid" else directory, command=command))


def test_snapshot_reentry_and_duplicate_completion(tmp_path):
    adapter = ControlledAdapter()
    launcher = ExperimentLauncher(adapter)
    request = command_request(fields(directory=str(tmp_path), command="Write-Output 'ok'"))
    assert launcher.launch(request)
    assert not launcher.launch(request)
    assert adapter.requests[0][0] == request
    adapter.requests[0][1]("未确认")
    adapter.requests[0][1](None)
    assert launcher.state.error == "未确认"
    assert launcher.launch(request)
    adapter.requests[-1][1](None)
    assert launcher.state.dispatched


def test_cancel_and_confirm_through_window(qt_app, tmp_path):
    class Cancel:
        def __init__(self, *args): pass
        def exec(self): return QDialog.DialogCode.Rejected
    class Accept(Cancel):
        def exec(self): return QDialog.DialogCode.Accepted
    store = TrialStore(tmp_path / "trials.json")
    trial_id = store.save(fields(directory=str(tmp_path), command="Write-Output 'ok'"))
    adapter = ControlledAdapter()
    launcher = ExperimentLauncher(adapter)
    window = ExperimentWindow(store, launcher, confirm=Cancel)
    window.start_trial()
    assert adapter.requests == []
    window.confirm = Accept
    window.start_trial()
    assert len(adapter.requests) == 1 and not window.launch_button.isEnabled()
    window.close()
    assert launcher.state.pending
    adapter.requests[0][1](None)
    assert store.trials()[0]["status"] == "待开始"
    assert store.snapshot()["selected_id"] == trial_id


def test_forms_keep_drafts_on_failure_and_cancel(qt_app, tmp_path):
    def denied(*args): raise OSError("disk full")
    store = TrialStore(tmp_path / "trials.json", writer=denied)
    dialog = TrialDialog(store)
    dialog.fields["name"].setText("仍保留的草稿")
    dialog.save()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.fields["name"].text() == "仍保留的草稿"
    assert "保存失败" in dialog.error.text()
    dialog.reject()
    assert store.trials() == []
    store.writer = lambda *args: None
    trial_id = store.save(fields())
    result = ResultDialog(store, store.trials()[0])
    result.result_text.setPlainText("结果")
    store.writer = denied
    result.save()
    assert result.result_text.toPlainText() == "结果" and "保存失败" in result.error.text()
    assert store.trials()[0]["records"] == []


def test_empty_search_keyboard_and_record_view(qt_app):
    store = demo_store()
    window = ExperimentWindow(store, ExperimentLauncher(ControlledAdapter()), demo=True)
    window.show()
    QTest.qWait(50)
    assert window.list.count() == 3 and window.heading.text() == "Pi 登录验证"
    window.search.setFocus()
    QTest.keyClicks(window.search, "AI")
    assert window.list.count() == 1
    window.search.setText("no matches")
    assert window.list.count() == 0 and "没有匹配" in window.list_empty.text()
    assert not window.launch_button.isEnabled()
    assert store.snapshot()["selected_id"] == window.current_id
    window.search.clear()
    window.list.setCurrentRow(1)
    assert window.heading.text() == "Commander 连接试验"
    store.record(window.current_id, "<b>plain text</b>", "继续", [])
    window.show_trial()
    assert window.records_layout.count() == 2
    assert window.minimumWidth() == 1000 and window.minimumHeight() == 700
    window.close()


def test_config_allows_recording_without_terminal(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"data_root": str(tmp_path)}), encoding="utf-8")
    assert load_config(config)["data_root"] == str(tmp_path)
    with pytest.raises(ValueError, match="terminal"):
        command_argv({}, CommandRequest("test", str(tmp_path), "echo x"))
