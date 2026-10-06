import time
from ai_workbench.lifecycle import Controller, Phase
from ai_workbench.local import LocalAdapter
from ai_workbench.storage import atomic_json, read_json
from ai_workbench.worker import ToolWorker


def test_pending_observation_failure_and_stale_status(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr("ai_workbench.local.subprocess.Popen", lambda *a, **k: None)
    adapter = LocalAdapter("commander", {"data_root": str(tmp_path), "pythonw": "runtime"}, tmp_path / "config.json")
    controller = Controller(adapter)
    assert controller.state.phase == Phase.UNKNOWN
    root = tmp_path / "runtime" / "commander"
    atomic_json(root / "state.json", {"updated_at": time.time(), "phase": "stopped", "running": False})
    adapter._poll()
    assert controller.start()
    request_id = adapter.pending_id
    atomic_json(root / "state.json", {"updated_at": time.time(), "phase": "starting", "running": True, "active_request": request_id, "detail": "等待浏览器授权"})
    adapter._poll()
    assert controller.state.pending and "授权" in controller.state.detail
    atomic_json(root / "state.json", {"updated_at": 0, "phase": "starting", "running": True})
    adapter._poll()
    assert controller.state.phase == Phase.UNKNOWN and not controller.stop()
    atomic_json(root / "state.json", {"updated_at": time.time(), "phase": "failed", "running": True, "completed_request": request_id, "error": "超时"})
    adapter._poll()
    assert controller.state.phase == Phase.FAILED and controller.state.running
    assert adapter.pending_id is None
    adapter.timer.stop()


def test_stale_observation_recovers_without_state_change(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr("ai_workbench.local.subprocess.Popen", lambda *a, **k: None)
    adapter = LocalAdapter("hermes", {"data_root": str(tmp_path), "pythonw": "runtime"}, tmp_path / "config.json")
    controller = Controller(adapter)
    path = adapter.root / "state.json"
    for timestamp, expected in ((time.time(), Phase.STOPPED), (0, Phase.UNKNOWN), (time.time(), Phase.STOPPED)):
        atomic_json(path, {"updated_at": timestamp, "phase": "stopped", "running": False})
        adapter._poll()
        assert controller.state.phase == expected
    adapter.timer.stop()


def test_worker_restart_completes_interrupted_request(tmp_path):
    from test_worker import Backend
    config = {"data_root": str(tmp_path), "hermes_home": str(tmp_path / "hermes")}
    root = tmp_path / "runtime" / "commander"
    atomic_json(root / "state.json", {"active_request": "interrupted"})
    backend = Backend()
    backend.target = backend.identity(90)
    worker = ToolWorker("commander", config, backend)
    worker.probe()
    snapshot = read_json(root / "state.json")
    assert snapshot["completed_request"] == "interrupted"
    assert snapshot["running"] and snapshot["phase"] == "failed"
    assert backend.launches == 0


def test_safe_startup_cause_reaches_both_theme_windows(qt_app, tmp_path, monkeypatch):
    import io
    from test_worker import Backend
    from ai_workbench.app import Workbench
    from ai_workbench.demo import DemoAdapter
    monkeypatch.setattr("ai_workbench.local.subprocess.Popen", lambda *a, **k: None)
    config = {"data_root": str(tmp_path), "pythonw": "runtime", "hermes_home": str(tmp_path / "hermes")}
    backend = Backend()
    worker = ToolWorker("commander", config, backend)
    worker.probe()
    adapter = LocalAdapter("commander", config, tmp_path / "config.json")
    controller = Controller(adapter)
    window = Workbench({"commander": controller, "hermes": Controller(DemoAdapter())})
    window.resize(620, 380)
    window.show()
    try:
        controller.start()
        request_path = adapter.root / "requests" / f"{adapter.pending_id}.json"
        worker.request(read_json(request_path))
        worker._output(io.BytesIO(b"Device startup failed: Device flow expired\n"))
        backend.launcher.poll = lambda: 1
        worker.probe()
        adapter._poll()
        row = window.rows["commander"]
        for theme in ("dark", "light"):
            window.set_theme(theme)
            qt_app.processEvents()
            assert "已过期" in row.error.text() and "1" in row.error.text()
            assert row.error.isVisible() and row.toggle.isEnabled()
            assert not row.toggle.isChecked()
            assert row.rect().contains(row.error.mapTo(row, row.error.rect().bottomRight()))
            assert window.rows["hermes"].toggle.isEnabled()
    finally:
        window.close()
        adapter.timer.stop()
