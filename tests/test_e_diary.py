"""Interface-level reliability tests with real text files and controlled generation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import zipfile

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest

from ai_workbench.e_diary.app import create_window
from ai_workbench.e_diary.library import DiaryLibrary, DiaryError, Conflict, load_json
from ai_workbench.e_diary.settings import Settings, style_resources
from ai_workbench.e_diary.cycles import Cycles
from ai_workbench.e_diary.sources import Sources, in_period
from ai_workbench.e_diary.reports import Reports, chart_for
from ai_workbench.e_diary.jobs import GenerationJobs


def test_npm_codex_launch_keeps_json_rpc_stream_unbuffered(tmp_path, monkeypatch):
    from ai_workbench.e_diary.codex import argv
    script = tmp_path / "node_modules/@openai/codex/bin/codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("// existing npm entry", encoding="utf-8")
    monkeypatch.setattr("ai_workbench.e_diary.codex.shutil.which", lambda _: "node.exe")
    command = argv(str(tmp_path / "codex.cmd"), "app-server", "--stdio")
    assert command == ["node.exe", str(script), "app-server", "--stdio"]


def fields(**values):
    return {"kind": "diary", "date": "2026-10-14", "title": "一天", "body": "散步后轻松了一些。", "tags": ["日常"], **values}


def test_library_dates_search_versions_external_conflict_and_trash(tmp_path):
    library = DiaryLibrary(tmp_path)
    first = library.save(fields())
    second = library.save(fields(title="同一天的第二篇", format=".txt"))
    assert first["id"] != second["id"]
    assert len(library.query(text="散步")) == 2
    updated = library.save(fields(date="2026-09-01", body="后来补记"), first["id"], first["hash"])
    assert updated["id"] == first["id"]
    assert library.version(first["id"], 0)["body"] == first["body"]
    path = tmp_path / "entries" / first["id"] / updated["file"]
    path.write_text("外部修改", encoding="utf-8")
    with pytest.raises(Conflict):
        library.save(fields(body="软件里的编辑"), first["id"], updated["hash"])
    assert path.read_text(encoding="utf-8") == "外部修改"
    reopened = DiaryLibrary(tmp_path)
    assert reopened.read(first["id"])["body"] == "外部修改"
    reopened.delete(first["id"])
    assert len(reopened.query()) == 1
    assert reopened.query(deleted=True)[0]["id"] == first["id"]
    reopened.restore(first["id"])
    assert len(reopened.query()) == 2
    reopened.delete(first["id"])
    with pytest.raises(DiaryError): reopened.purge(first["id"])
    reopened.purge(first["id"], confirmed=True)
    assert not reopened.query(deleted=True)


def test_failed_descriptor_commit_keeps_previous_text(tmp_path, monkeypatch):
    import ai_workbench.e_diary.library as module
    library = DiaryLibrary(tmp_path)
    original = library.save(fields())
    def fail(*args): raise OSError("disk full")
    monkeypatch.setattr(module, "atomic_json", fail)
    with pytest.raises(OSError):
        library.save(fields(body="未保存"), original["id"], original["hash"])
    assert DiaryLibrary(tmp_path).read(original["id"])["body"] == original["body"]


def test_malformed_data_is_not_overwritten(tmp_path):
    library = DiaryLibrary(tmp_path)
    record = library.save(fields())
    path = tmp_path / "entries" / record["id"] / "record.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(DiaryError): DiaryLibrary(tmp_path)
    assert path.read_text() == "broken"


def test_live_style_reloads_and_missing_resources_fail(tmp_path):
    prose = tmp_path / "prose.md"
    prose.write_text("直接写", encoding="utf-8")
    config = {"prose_path": str(prose)}
    before, hashes = style_resources(config)
    prose.write_text("改成更具体的语言", encoding="utf-8")
    after, new_hashes = style_resources(config)
    assert before != after and hashes != new_hashes
    with pytest.raises(DiaryError): style_resources(config, True)


def test_settings_merge_latest_external_document(tmp_path):
    settings = Settings(tmp_path)
    settings.update()
    path = tmp_path / "settings.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["another_consumer"] = {"keep": True}
    path.write_text(json.dumps(document), encoding="utf-8")
    settings.update(theme="dark")
    assert json.loads(path.read_text(encoding="utf-8"))["another_consumer"] == {"keep": True}


def test_dirty_diary_selection_survives_saved_signal_refresh(qt_app):
    window = create_window(demo=True)
    old_id = window.editor.record["id"]
    target_id = window.list.item(1).data(Qt.UserRole)
    window.editor.body.setPlainText("切换前尚未自动保存的编辑")
    window.select_entry(window.list.item(1))
    assert window.editor.record["id"] == target_id
    assert window.list.currentItem().data(Qt.UserRole) == target_id
    assert window.library.read(old_id)["body"] == "切换前尚未自动保存的编辑"
    window.close()


def test_history_restores_revision_owned_metadata(tmp_path):
    library = DiaryLibrary(tmp_path)
    first = library.save(fields(kind="personal", format=".txt", tags=["旧标签"], sources=[{"id": "old-source"}],
                                provenance={"style_fingerprints": {"zf": "old"}}))
    library.save(fields(kind="personal", format=".md", tags=["新标签"], sources=[{"id": "new-source"}],
                        provenance={"style_fingerprints": {"zf": "new"}}), first["id"], first["hash"])
    previous = library.version(first["id"], 0)
    assert previous["format"] == ".txt" and previous["tags"] == ["旧标签"]
    assert previous["sources"] == [{"id": "old-source"}]
    assert previous["provenance"]["style_fingerprints"]["zf"] == "old"
    restored = library.save(previous, first["id"], library.read(first["id"])["hash"])
    assert restored["format"] == ".txt" and restored["sources"] == previous["sources"]


def test_history_clears_metadata_absent_in_earlier_revision():
    library = DiaryLibrary()
    first = library.save(fields(kind="personal"))
    latest = library.save(fields(kind="personal", sources=[{"id": "new"}], charts=[{"values": [1]}],
        period={"start": "2026-10-01", "end": "2026-10-15"}, provenance={"style": "new"}), first["id"], first["hash"])
    restored = library.save(library.version(first["id"], 0), first["id"], latest["hash"])
    assert restored["sources"] == [] and restored["charts"] == []
    assert restored["provenance"] == {} and restored["period"] == {}


def test_git_intake_includes_chinese_changed_filename(tmp_path):
    import subprocess
    def run(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.name", "Diary test")
    run("config", "user.email", "diary-test@example.invalid")
    (tmp_path / "研究笔记.md").write_text("有证据的研究记录", encoding="utf-8")
    run("add", "研究笔记.md")
    run("commit", "-qm", "test source")
    source = Sources(Settings(), DiaryLibrary())
    docs = source._git(tmp_path, "2000-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00")
    assert any(d["title"] == "研究笔记.md" and d["body"] == "有证据的研究记录" for d in docs)


def test_cycle_time_change_preserves_next_calendar_boundary():
    settings = Settings()
    rules = deepcopy(settings.data["cycles"])
    for rule in rules.values(): rule["enabled"] = False
    rules["development"].update(enabled=True, days=7, anchor="2026-10-01T08:00:00+08:00", last_end="2026-10-08T09:00:00+08:00")
    settings.update(cycles=rules)
    request = Cycles(settings).due(datetime.fromisoformat("2026-10-15T08:00:00+08:00"))
    assert request["start"] == "2026-10-08T09:00:00+08:00"
    assert request["end"] == "2026-10-15T08:00:00+08:00"


def test_demo_cannot_read_added_sources_imports_or_extra_paths(qt_app, tmp_path, monkeypatch):
    window = create_window(demo=True)
    window.settings.update(sources=[{"id": "real", "path": str(tmp_path), "enabled": True, "type": "git"}])
    window.config["read_codex"] = True
    def fail(*args): raise AssertionError("demo attempted real intake")
    monkeypatch.setattr(window.sources, "_git", fail)
    monkeypatch.setattr(window.sources, "_sessions", fail)
    request = {"kind": "development", "start": "2020-01-01T00:00:00+08:00", "end": "2030-01-01T00:00:00+08:00", "extra_paths": [str(tmp_path / "private.txt")]}
    collected = window.sources.collect(request, threading.Event(), lambda _: None)
    assert collected["documents"]
    assert all(d["origin"] in ("diary", "development", "work") for d in collected["documents"])
    with pytest.raises(DiaryError, match="演示模式"):
        window.sources.import_file(tmp_path / "private.txt")
    window.close()


def test_codex_drains_late_thread_event_before_returning(tmp_path, monkeypatch):
    import io
    from ai_workbench.e_diary.codex import CodexAdapter
    class DelayedStream(io.StringIO):
        def __iter__(self):
            time.sleep(.05)
            while line := self.readline():
                yield line
    class Process:
        returncode = 0
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = DelayedStream(json.dumps({"type": "thread.started", "thread_id": "late-thread"}) + "\n")
            self.stderr = io.StringIO()
        def poll(self): return 0
    def start(command, directory):
        (directory / "response.json").write_text(json.dumps({"title": "test", "body": "body", "files": []}), encoding="utf-8")
        return Process()
    monkeypatch.setattr("ai_workbench.e_diary.codex.popen", start)
    result = CodexAdapter({"codex_cli": "codex.exe"}).generate("prompt", tmp_path, threading.Event(), lambda _: None)
    assert result["thread_ids"] == ["late-thread"]


def test_regeneration_does_not_replace_title_edit_during_generation(qt_app, tmp_path):
    ready, release = threading.Event(), threading.Event()
    class Adapter:
        def generate(self, *args):
            ready.set()
            release.wait(3)
            return {"title": "AI replacement", "body": "new body", "files": []}
    window = create_window({"staging_root": str(tmp_path)}, demo=True)
    window.jobs.adapter = Adapter()
    existing = window.library.query(kind="personal")[0]
    window.jobs.submit({"kind": "personal", "start": "2020-01-01T00:00:00+08:00", "end": "2030-01-01T00:00:00+08:00", "entry_id": existing["id"]})
    assert ready.wait(3)
    window.library.save(dict(existing, title="我的新标题"), existing["id"], existing["hash"])
    release.set()
    wait_job(qt_app, window.jobs)
    assert window.jobs.state["error"]
    assert window.library.read(existing["id"])["title"] == "我的新标题"
    window.close()


def test_cycles_merge_gaps_failure_and_independent_switches(tmp_path):
    settings = Settings(tmp_path)
    anchor = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
    rules = deepcopy(settings.data["cycles"])
    for rule in rules.values(): rule["anchor"] = anchor.isoformat()
    rules["work"]["enabled"] = False
    settings.update(cycles=rules)
    cycles = Cycles(settings)
    at = anchor + timedelta(days=35, hours=3)
    request = cycles.due(at)
    assert request["kind"] == "development"
    assert request["start"] == anchor.isoformat()
    cycles.completed(request, False)
    assert settings.data["cycles"]["development"]["last_end"] is None
    assert cycles.due(at)["kind"] == "personal"
    cycles.blocked.clear()
    cycles.completed(request, True)
    assert cycles.due(at)["kind"] == "personal"
    assert Settings(tmp_path).data["cycles"]["development"]["last_end"] == request["end"]


def test_chatgpt_branches_zip_dedup_and_time_filter(tmp_path):
    library, settings = DiaryLibrary(tmp_path / "data"), Settings(tmp_path / "data")
    sources = Sources(settings, library, {"read_codex": False})
    value = [{"id": "conversation", "title": "分支", "mapping": {
        "a": {"parent": None, "children": ["b", "c"], "message": {"author": {"role": "user"}, "content": {"parts": ["原始想法"]}, "create_time": 1791936000}},
        "b": {"parent": "a", "children": [], "message": {"author": {"role": "assistant"}, "content": {"parts": ["分支一"]}, "create_time": 1791936001}},
        "c": {"parent": "a", "children": [], "message": {"author": {"role": "assistant"}, "content": {"parts": ["分支二"]}, "create_time": 1791936002}}}}]
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("conversations.json", json.dumps(value))
    assert sources.import_file(archive) == 3
    assert sources.import_file(archive) == 0
    imported = load_json(library.root / "imports" / (settings.data["imports"][0]["id"] + ".json"))["documents"]
    assert imported[1]["parent"] == "a" and imported[2]["parent"] == "a"
    assert in_period("2026-10-14", "2026-10-14T00:00:00+08:00", "2026-10-15T00:00:00+08:00")


def bundle():
    return {"start": "2026-10-01T00:00:00+08:00", "end": "2026-10-15T00:00:00+08:00", "warnings": [],
        "documents": [{"id": "a", "title": "记录", "origin": "diary", "at": "2026-10-14", "body": "一些记录"}]}


def test_reports_atomic_files_pdf_images_and_path_validation(qt_app, tmp_path):
    reports = Reports(Settings())
    result = {"title": "汇报", "body": "完成与计划分开。", "files": [
        {"name": "数据.csv", "content": "日期,篇数\n2026-10-14,1"},
        {"name": "打印.pdf", "content": "# 记录\n\n可读的中文正文"},
        {"name": "图.png", "content": ""}, {"name": "图.svg", "content": ""}]}
    report = reports.deliver(result, bundle(), tmp_path, "job-one")
    package = Path(report["path"])
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    assert doc.load(str(package / "打印.pdf")) == QPdfDocument.Error.None_
    assert doc.pageCount() >= 1
    assert not doc.render(0, __import__('PySide6.QtCore', fromlist=['QSize']).QSize(400, 600)).isNull()
    doc.close()
    assert (package / "图.png").read_bytes().startswith(b"\x89PNG")
    result["files"] = [{"name": "../escape.md", "content": "bad"}]
    with pytest.raises(DiaryError): reports.deliver(result, bundle(), tmp_path, "job-two")
    assert not (tmp_path / "e-Diary-job-two").exists()
    assert chart_for(bundle())["values"] == [0, 1]


def test_summary_period_overlap_in_personal_sources(tmp_path):
    library, settings = DiaryLibrary(tmp_path), Settings(tmp_path)
    library.save(fields(kind="development", date="2026-10-15", period={"start": "2026-10-01T00:00:00+08:00", "end": "2026-10-15T00:00:00+08:00"}))
    data = Sources(settings, library).collect({"kind": "personal", "start": "2026-10-01T00:00:00+08:00", "end": "2026-10-15T00:00:00+08:00"}, threading.Event(), lambda _: None)
    assert len(data["documents"]) == 1


def test_codex_pagination_dates_and_self_exclusion(tmp_path, monkeypatch):
    calls = []
    stamp = int(datetime(2026, 10, 14, tzinfo=timezone.utc).timestamp())
    class Server:
        def __init__(self, *args): pass
        def close(self): pass
        def request(self, method, params):
            calls.append((method, params))
            if method == "thread/list":
                if params.get("archived"):
                    return {"data": [], "nextCursor": None}
                if params.get("cursor"):
                    return {"data": [{"id": "own", "updatedAt": stamp}], "nextCursor": None}
                return {"data": [{"id": "user", "name": "用户会话", "updatedAt": stamp + 7 * 86400}], "nextCursor": "next"}
            if params.get("cursor"):
                return {"data": [{"id": "old", "startedAt": stamp - 30 * 86400, "items": []}], "nextCursor": None}
            return {"data": [{"id": "current", "startedAt": stamp, "items": [
                {"type": "userMessage", "content": [{"type": "text", "text": "想做一个功能"}]},
                {"type": "agentMessage", "text": "只是建议，还没完成"}]}], "nextCursor": "turn-next"}
    monkeypatch.setattr("ai_workbench.e_diary.sources.AppServer", Server)
    library, settings = DiaryLibrary(tmp_path), Settings(tmp_path)
    settings.update(own_threads=["own"])
    source = Sources(settings, library, {"codex_cli": "existing-cli", "staging_root": str(tmp_path)})
    docs = source._sessions("2026-10-01T00:00:00+00:00", "2026-10-15T00:00:00+00:00", threading.Event())
    assert len(docs) == 1 and docs[0]["id"] == "codex:user:current"
    assert "用户输入" in docs[0]["body"] and "助手记录" in docs[0]["body"]
    assert len([m for m, p in calls if m == "thread/list"]) == 3
    assert not any(p.get("threadId") == "own" for m, p in calls)


def wait_job(app, jobs, timeout=5):
    deadline = time.monotonic() + timeout
    while jobs.state["pending"] and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert not jobs.state["pending"]


def test_job_failure_cancellation_and_duplicate_completion(qt_app, tmp_path):
    class Adapter:
        mode = "success"
        def generate(self, prompt, directory, cancelled, progress):
            if self.mode == "fail": raise DiaryError("controlled failure")
            if self.mode == "wait":
                cancelled.wait(3)
                raise DiaryError("任务已取消")
            return {"title": "生成", "body": "有依据的正文", "files": []}
    window = create_window({"staging_root": str(tmp_path)}, demo=True)
    adapter = Adapter()
    window.jobs.adapter = adapter
    request = {"kind": "personal", "start": "2026-09-01T00:00:00+08:00", "end": "2026-11-01T00:00:00+08:00"}
    job_id = window.jobs.submit(request)
    with pytest.raises(DiaryError): window.jobs.submit(request)
    wait_job(qt_app, window.jobs)
    count = len(window.library.query(kind="personal"))
    window.jobs._commit({"job_id": job_id})
    assert len(window.library.query(kind="personal")) == count
    adapter.mode = "fail"
    window.jobs.submit(request)
    wait_job(qt_app, window.jobs)
    assert "controlled failure" in window.jobs.state["error"]
    adapter.mode = "wait"
    window.jobs.submit(request)
    window.jobs.cancel()
    wait_job(qt_app, window.jobs)
    assert "取消" in window.jobs.state["error"]
    window.close()


def test_native_diary_edit_theme_periods_and_runtime_persistence(qt_app, tmp_path):
    window = create_window({"data_root": str(tmp_path), "read_codex": False})
    window.show()
    window.new_entry()
    window.editor.title.setText("测试日记")
    window.editor.body.setPlainText("今天有一点疲惫。")
    window.editor.tags.setText("日常, 回顾")
    assert window.editor.save()
    entry_id = window.editor.record["id"]
    assert window.library.read(entry_id)["body"] == "今天有一点疲惫。"
    window.apply_theme("dark")
    assert Settings(tmp_path).data["theme"] == "dark"
    window.navigate("personal")
    assert window.list_heading.text() == "个人回顾"
    window.navigate("cycles")
    assert window.navigation["cycles"].isChecked()
    window.close()
    reopened = create_window({"data_root": str(tmp_path), "read_codex": False})
    assert reopened.library.read(entry_id)["title"] == "测试日记"
    reopened.close()
