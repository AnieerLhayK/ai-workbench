"""Exercise provider choices through the same seam used by desktop callers."""
import json
import threading
import zipfile

import pytest

from ai_workbench.e_chatter.files import ChatterError
from ai_workbench.e_chatter.providers import Providers, selection
from ai_workbench.e_chatter.service import Service
from ai_workbench.e_chatter import migration


class Controlled:
    def __init__(self):
        self.requests = []

    def account(self):
        return {"connected": True, "label": "controlled", "models": [
            {"id": "a", "name": "A", "default": True, "efforts": [{"id": "high", "name": "High"}]},
            {"id": "b", "name": "B", "efforts": []}]}

    def generate(self, request, cancelled, emit):
        self.requests.append(request)
        emit("controlled")
        return dict(reply="controlled", status="completed", files=[], diagnosis="", handoff="", build_intake="")

    def close(self):
        pass


def test_codex_turn_choice_does_not_report_thread_default_as_actual(tmp_path, monkeypatch):
    from ai_workbench.e_chatter.codex import Codex
    class Rpc:
        def __init__(self):
            self.lock, self.events = threading.RLock(), {}
        def request(self, method, params, **kwargs):
            if method == "thread/start":
                return {"thread": {"id": "t"}, "model": "chosen", "reasoningEffort": "medium"}
            if method == "turn/start":
                assert params["effort"] == "high"
                self.events["t"].put({"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": '{"reply":"ok"}'}}})
                self.events["t"].put({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
                return {"turn": {"id": "turn"}}
            return {}
    rpc = Rpc()
    monkeypatch.setattr(Codex, "connect", lambda self: rpc)
    request = {"payload": {"role": "chat"}, "model": "chosen", "execution": {"model": "chosen", "effort": "high"}}
    Codex(tmp_path, "synthetic").generate(request, threading.Event(), lambda text: None)
    assert request["execution"]["effort"] == "high"
    assert "actual_effort" not in request["execution"]


def test_provider_exit_reports_safe_code_without_raw_output(tmp_path):
    import sys
    from ai_workbench.e_chatter.codex import Rpc
    rpc = Rpc([sys.executable, "-u", "-c", "import sys; sys.stdin.readline(); print('synthetic-private-token',file=sys.stderr); sys.exit(17)"], tmp_path, label="Harness fixture", jsonrpc=True)
    try:
        with pytest.raises(ChatterError, match="退出码 17") as error:
            rpc.request("synthetic/status", {})
        assert "synthetic-private-token" not in str(error.value)
    finally:
        rpc.close()


def test_session_agent_preferences_survive_reopen_without_cross_talk(tmp_path):
    root = tmp_path / "data"
    s = Service(root)
    first, second = s.session(), s.session()
    s.models(first["id"], "codex", "a", "high")
    s.models(first["id"], "deepseek", "b")
    s.select_agent("deepseek")
    hub = Providers(s, {"codex": Controlled, "deepseek": Controlled})
    assert hub.bind(first["id"]) == {"agent": "deepseek", "model": "b", "effort": None}
    assert hub.bind(second["id"])["model"] == "a"
    s.store.close()
    s = Service(root)
    s.select_agent("codex")
    assert Providers(s, {"codex": Controlled}).bind(first["id"])["effort"] == "high"
    s.store.close()


def test_legacy_global_model_is_seeded_only_once(tmp_path):
    s = Service(tmp_path)
    session = s.session()
    value = s.store.get("sessions", session["id"])
    value.pop("model_preferences")
    s.store.db.execute("UPDATE documents SET body=? WHERE kind='sessions' AND id=?", (json.dumps(value), session["id"]))
    s.store.db.commit()
    s.settings(model="a")
    s.store.close()
    s = Service(tmp_path)
    assert s.store.get("sessions", session["id"])["model_preferences"]["codex"]["model"] == "a"
    s.models(session["id"], "codex", "b")
    s.store.close()
    s = Service(tmp_path)
    assert s.store.get("sessions", session["id"])["model_preferences"]["codex"]["model"] == "b"
    s.store.close()


@pytest.mark.parametrize("value", [{"model": "gone"}, {"model": "b", "effort": "high"}])
def test_unavailable_selection_never_falls_back(value):
    with pytest.raises(ChatterError):
        selection(Controlled().account()["models"], value)


def test_engineering_snapshot_and_global_switch_are_fixed():
    s = Service()
    session = s.session()
    confirmation = s.prepare_engineering(session["id"], "generator")
    task = s.start_engineering(session["id"], "generator", confirmation["token"])
    s.models(session["id"], "codex", "b", task_id=task["id"])
    hub = Providers(s, {"codex": Controlled, "deepseek": Controlled})
    bound = hub.bind(session["id"], task["id"], {"model": "b"})
    s.store.update("tasks", task["id"], execution=bound)
    with pytest.raises(ChatterError):
        s.select_agent("deepseek")
    with pytest.raises(ChatterError):
        s.models(session["id"], "codex", "a", task_id=task["id"])
    s.models(session["id"], "codex", "a")
    assert hub.bind(session["id"], task["id"])["model"] == "b"
    s.cancel_task(task["id"])
    s.select_agent("deepseek")


def test_migration_keeps_model_preferences_but_not_local_authorization(tmp_path):
    s = Service(tmp_path / "source")
    session = s.session()
    s.models(session["id"], "deepseek", "a", "high")
    s.authorize_provider(session["id"], "deepseek")
    s.settings(deepseek_cli="private-runtime", deepseek_auth="api_key")
    (s.root / "providers").mkdir()
    (s.root / "providers/credentials.yaml").write_text("synthetic-credential")
    archive = tmp_path / "transfer.zip"
    migration.export_package(s, archive)
    with zipfile.ZipFile(archive) as z:
        raw = z.read("library.json")
        assert b"private-runtime" not in raw and b"synthetic-credential" not in raw
        assert b"authorized_agents" not in raw
        assert not any(n.startswith("providers/") for n in z.namelist())
    target = Service(tmp_path / "target")
    preview = migration.preview_package(target, archive)
    migration.import_package(target, preview["token"])
    assert target.store.rows("sessions")[0]["model_preferences"]["deepseek"]["effort"] == "high"
    assert "deepseek" not in target.store.rows("sessions")[0].get("authorized_agents", [])


def test_request_execution_is_captured_in_message_and_diagnostic():
    s = Service()
    session = s.session()
    request = s.prepare_request(session["id"], "synthetic writing request")
    request["execution"] = {"agent": "codex", "model": "a", "effort": "high"}
    provider = Controlled()
    s.complete(request, provider.generate(request, threading.Event(), lambda _: None))
    assert s.store.rows("messages")[-1]["metadata"]["execution"] == request["execution"]


def test_archive_named_metadata_read_is_bounded(tmp_path):
    import struct
    from ai_workbench.e_chatter.harness_archive import read_file
    bad = tmp_path / "bad.asar"
    bad.write_bytes(struct.pack("<II", 4, 17*1024*1024))
    with pytest.raises(ChatterError):
        read_file(bad, "package.json")


def test_delayed_login_url_is_opened_once_without_leaking_into_ui(qt_app):
    from ai_workbench.e_chatter.app import Bridge

    class Delayed(Controlled):
        phase = "initializing"

        def account(self):
            return super().account() | {"connected": False, "attempt": {
                "id": "synthetic-attempt", "phase": self.phase,
                **({"authorizeUrl": "https://platform.deepseek.com/dsh/authorize?test=synthetic"} if self.phase == "waiting-browser" else {})}}

    s = Service()
    adapter = Delayed()
    bridge = Bridge(s, provider=adapter)
    bridge.provider = Providers(s, {"deepseek": lambda: adapter})
    bridge.open_url.disconnect()  # Test must never launch an actual browser.
    opened = []
    bridge.open_url.connect(opened.append)
    try:
        first = bridge.execute("account.status", {"agent": "deepseek"})
        assert first["attempt"]["phase"] == "initializing" and opened == []
        adapter.phase = "waiting-browser"
        state = bridge.execute("account.status", {"agent": "deepseek"})
        bridge.execute("account.status", {"agent": "deepseek"})
        assert len(opened) == 1
        assert state["attempt"] == {"id": "synthetic-attempt", "phase": "waiting-browser"}
    finally:
        bridge.close()
        s.store.close()
