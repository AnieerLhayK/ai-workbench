"""Capability-boundary tests use synthetic processes, never connected services."""
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from ai_workbench.e_diary.codex import CodexAdapter
from ai_workbench.e_chatter.service import Service
from ai_workbench.e_chatter.files import ChatterError
from ai_workbench import codex_isolation as isolation


@pytest.fixture
def metadata(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        value = (b"--ignore-user-config --ignore-rules --output-schema" if "--help" in command else
                 json.dumps({"models": [{"slug": "synthetic", "shell_type": "enabled", "experimental_supported_tools": ["shell"]}]}).encode())
        return SimpleNamespace(returncode=0, stdout=value)
    monkeypatch.setattr("subprocess.run", run)
    return calls


def test_diary_does_not_inherit_tools_before_submitting_material(tmp_path, monkeypatch, metadata):
    def inspect(command, directory):
        assert "--ignore-user-config" in command, "generation inherits user tool configuration"
        assert "--ignore-rules" in command
        assert "mcp_servers={}" in command
        raise RuntimeError("controlled stop before model submission")

    monkeypatch.setattr("ai_workbench.e_diary.codex.popen", inspect)
    with pytest.raises(RuntimeError, match="controlled stop"):
        CodexAdapter({"codex_cli": "synthetic-codex.exe"}).generate(
            "synthetic evidence", tmp_path, threading.Event(), lambda _: None)


def test_docx_rejects_declared_expansion_before_read(tmp_path, monkeypatch):
    class Archive:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def getinfo(self, name): return SimpleNamespace(file_size=17 * 1024 * 1024)
        def read(self, *args): pytest.fail("oversized XML reached unbounded decompression")
        def open(self, *args): pytest.fail("oversized XML reached decompression")

    source = tmp_path / "synthetic.docx"
    source.write_bytes(b"synthetic archive marker")
    before = source.read_bytes()
    service = Service(tmp_path / "library")
    try:
        monkeypatch.setattr("zipfile.ZipFile", lambda _: Archive())
        with pytest.raises(ChatterError, match="16 MB"):
            service.attach(source)
        assert not service.materials
        assert source.read_bytes() == before
    finally:
        service.store.close()


@pytest.mark.parametrize("application", ["diary", "experiment"])
def test_exec_generation_catalog_and_unsafe_events(tmp_path, monkeypatch, metadata, application):
    from ai_workbench.experiment_box.assistant import CodexAssistant
    from ai_workbench.e_diary.library import DiaryError
    from ai_workbench.experiment_box.model import StoreError
    error_type = DiaryError if application == "diary" else StoreError
    module = "ai_workbench.e_diary.codex" if application == "diary" else "ai_workbench.experiment_box.assistant"
    class Process:
        returncode = 0
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(json.dumps({"type": "item.completed", "item": {"type": "dynamic_tool_call"}}) + "\n")
            self.stderr = io.StringIO()
        def poll(self): return 0

    def start(command, directory):
        assert "--ignore-user-config" in command and "--ignore-rules" in command
        assert all(f"features.{name}=false" in command for name in isolation.DISABLED)
        catalog = json.loads((directory / "models.json").read_text())
        model = catalog["models"][0]
        assert model["shell_type"] == "disabled" and model["apply_patch_tool_type"] is None
        assert model["experimental_supported_tools"] == []
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({"title": "test", "body": "not accepted", "files": []}))
        return Process()
    monkeypatch.setattr(module + ".popen", start)
    with pytest.raises(error_type):
        if application == "diary":
            CodexAdapter({"codex_cli": "synthetic"}).generate("evidence", tmp_path, threading.Event(), lambda _: None)
        else:
            CodexAssistant({"codex_cli": "synthetic"}).generate({"images": []}, tmp_path, threading.Event())


@pytest.mark.parametrize("application", ["diary", "experiment", "chatter"])
@pytest.mark.parametrize("failure", ["unsupported", "malformed"])
def test_isolation_preflight_failure_never_submits_material(tmp_path, monkeypatch, application, failure):
    from ai_workbench.e_chatter.codex import Codex
    from ai_workbench.experiment_box.assistant import CodexAssistant
    def run(*args, **kwargs):
        return SimpleNamespace(returncode=0 if failure == "malformed" else 1, stdout=b"not a catalog")
    monkeypatch.setattr("subprocess.run", run)
    def forbidden(*args, **kwargs): pytest.fail("model process started after failed preflight")
    monkeypatch.setattr("ai_workbench.e_diary.codex.popen", forbidden)
    monkeypatch.setattr("ai_workbench.experiment_box.assistant.popen", forbidden)
    monkeypatch.setattr("ai_workbench.e_chatter.codex.Rpc", forbidden)
    with pytest.raises(ValueError, match="Codex") as error:
        if application == "diary":
            CodexAdapter({"codex_cli": "synthetic"}).generate("evidence", tmp_path, threading.Event(), lambda _: None)
        elif application == "experiment":
            CodexAssistant({"codex_cli": "synthetic"}).generate({}, tmp_path, threading.Event())
        else:
            Codex(tmp_path, "synthetic").connect()
    assert "not a catalog" not in str(error.value)


@pytest.mark.parametrize("effective", ["disabled", "still_enabled", "malformed"])
def test_chatter_checks_merged_mcp_before_thread(tmp_path, monkeypatch, metadata, effective):
    from ai_workbench.e_chatter.codex import Codex
    calls, instances = [], []
    class Rpc:
        def __init__(self, command, directory):
            self.command = command[:]
            self.process = SimpleNamespace(poll=lambda: None)
            self.closed = False
            instances.append(self)
        def _send(self, message): pass
        def close(self): self.closed = True
        def request(self, method, params):
            calls.append(method)
            if method == "initialize": return {}
            if method == "config/read":
                if effective == "malformed": return {"config": {"mcp_servers": []}}
                enabled = not (len(instances) == 2 and effective == "disabled")
                return {"config": {"features": dict.fromkeys(isolation.DISABLED, False),
                                   "mcp_servers": {"write_capable": {"enabled": enabled}}}}
            if method == "model/list": return {"data": []}
            pytest.fail("model thread started before isolation")
    monkeypatch.setattr("ai_workbench.e_chatter.codex.Rpc", Rpc)
    provider = Codex(tmp_path, "synthetic")
    if effective == "disabled":
        provider.connect()
        assert len(instances) == 2 and instances[0].closed
        assert "mcp_servers.write_capable.enabled=false" in instances[1].command
        provider.close()
    else:
        with pytest.raises(ChatterError):
            provider.generate({"payload": {"role": "chat"}}, threading.Event(), lambda _: None)
        assert all(instance.closed for instance in instances)
    assert "thread/start" not in calls and "turn/start" not in calls


@pytest.mark.parametrize("tool_type", [None, "mcpToolCall", "dynamic_tool_call"])
def test_chatter_stream_control_and_tool_interrupt(tmp_path, monkeypatch, metadata, tool_type):
    from ai_workbench.e_chatter.codex import Codex
    calls = []
    class Rpc:
        def __init__(self, *args):
            self.process = SimpleNamespace(poll=lambda: None)
            self.lock, self.events = threading.RLock(), {}
        def _send(self, message): pass
        def close(self): pass
        def request(self, method, params, **kwargs):
            calls.append(method)
            if method == "initialize": return {}
            if method == "config/read": return {"config": {"features": dict.fromkeys(isolation.DISABLED, False)}}
            if method == "model/list": return {"data": []}
            if method == "thread/start": return {"thread": {"id": "synthetic"}}
            if method == "turn/start":
                event = self.events["synthetic"]
                if tool_type:
                    event.put({"method": "item/started", "params": {"item": {"type": tool_type}}})
                else:
                    raw = json.dumps({"reply": "synthetic reply", "status": "completed", "files": []})
                    event.put({"method": "item/agentMessage/delta", "params": {"delta": raw}})
                    event.put({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
                return {"turn": {"id": "turn"}}
            return {}
    monkeypatch.setattr("ai_workbench.e_chatter.codex.Rpc", Rpc)
    provider, stream = Codex(tmp_path, "synthetic"), []
    try:
        if tool_type:
            with pytest.raises(ChatterError): provider.generate({"payload": {"role": "chat"}}, threading.Event(), stream.append)
            assert "turn/interrupt" in calls
        else:
            assert provider.generate({"payload": {"role": "chat"}}, threading.Event(), stream.append)["reply"] == "synthetic reply"
            assert stream[-1] == "synthetic reply"
        assert not provider.rpc.events
    finally: provider.close()


@pytest.mark.parametrize("name", ["mcp_tool_call", "mcpToolCall", "web_search", "webSearch", "fileChange", "command_execution"])
def test_tool_event_aliases(name):
    assert isolation.is_tool_event({"item": {"type": name}})
    assert not isolation.is_tool_event({"item": {"type": "agentMessage"}})


@pytest.mark.parametrize("config", [{}, {"features": []}, {"mcp_servers": {"unsafe.name": {}}},
                                      {"mcp_servers": {"bad": None}}, {"features": dict.fromkeys(isolation.DISABLED, True)}])
def test_configuration_fails_closed(config):
    with pytest.raises(isolation.IsolationError): isolation.verify_config(config)


@pytest.mark.parametrize("xml_size, encoding", [(24, "utf-8"), (16 * 1024 * 1024, "utf-8"), (24, "utf-16")])
def test_docx_accepts_normal_and_exact_limit(tmp_path, xml_size, encoding):
    import zipfile
    xml = ("<d>" + "x" * (xml_size - 7) + "</d>").encode(encoding)
    source = tmp_path / "normal.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    service = Service(tmp_path / "library")
    before = source.read_bytes()
    try:
        result = service.attach(source)
        assert service.materials[result["id"]]["text"] == "x" * (xml_size - 7)
        assert source.read_bytes() == before
    finally: service.store.close()


def test_docx_bounded_read_rejects_actual_overflow(tmp_path, monkeypatch):
    class Stream(io.BytesIO):
        def read(self, size=-1):
            assert size == 16 * 1024 * 1024 + 1
            return b"x" * size
    class Archive:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def getinfo(self, name): return SimpleNamespace(file_size=1)
        def open(self, member): return Stream()
    monkeypatch.setattr("zipfile.ZipFile", lambda _: Archive())
    source = tmp_path / "overflow.docx"
    source.write_bytes(b"synthetic marker")
    service = Service(tmp_path / "library")
    try:
        with pytest.raises(ChatterError, match="16 MB"): service.attach(source)
        assert not service.materials
    finally: service.store.close()


@pytest.mark.parametrize("kind", ["broken_zip", "missing_xml", "invalid_xml", "oversize"])
def test_docx_invalid_input_preserves_state_and_source(tmp_path, kind):
    import zipfile
    source = tmp_path / "invalid.docx"
    if kind == "broken_zip": source.write_bytes(b"broken zip")
    else:
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("missing" if kind == "missing_xml" else "word/document.xml",
                             b"x" * (16 * 1024 * 1024 + 1) if kind == "oversize" else b"<invalid")
    before = source.read_bytes()
    service = Service(tmp_path / "library")
    try:
        with pytest.raises(ChatterError): service.attach(source)
        assert not service.materials and source.read_bytes() == before
    finally: service.store.close()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_docx_rejects_entity_expansion_before_xml_tree(tmp_path, encoding):
    import zipfile
    xml = ('<?xml version="1.0" encoding="' + encoding + '"?><!DOCTYPE d [<!ENTITY a "' +
           "x" * 1_000_000 + '">]><d>' + "&a;" * 20 + "</d>").encode(encoding)
    source = tmp_path / "entities.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    service = Service(tmp_path / "library")
    try:
        with pytest.raises(ChatterError, match="DTD"): service.attach(source)
        assert not service.materials
    finally: service.store.close()
