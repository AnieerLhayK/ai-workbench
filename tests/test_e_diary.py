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
from ai_workbench.e_diary.settings import Settings, StyleResources, style_resources
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


def style_source(tmp_path):
    source = tmp_path / "source"
    (source / "references").mkdir(parents=True)
    (source / "prompts").mkdir()
    (source / "SKILL.md").write_text("original name\n`references/voice.md`", encoding="utf-8")
    (source / "references/voice.md").write_text("voice\n`prompts/write.md`", encoding="utf-8")
    (source / "prompts/write.md").write_text("write", encoding="utf-8")
    (source / "private-corpus.txt").write_text("not a resource", encoding="utf-8")
    return source


def test_style_mirror_is_explicit_independent_complete_and_tamper_checked(tmp_path):
    source = style_source(tmp_path)
    config = {"data_root": str(tmp_path / "data"), "zf_root": str(source)}
    resources = StyleResources(config)
    assert not resources.status()["available"]
    with pytest.raises(DiaryError, match="尚未同步"):
        style_resources(config, True)
    first = resources.sync()
    assert set(resources.load()) == {"SKILL.md", "references/voice.md", "prompts/write.md"}
    before = style_resources(config, True)
    (source / "references/voice.md").write_text("new voice", encoding="utf-8")
    assert style_resources(config, True) == before
    second = resources.sync()
    assert second["version"] != first["version"]
    assert resources.load()["references/voice.md"] == "new voice"
    source.rename(tmp_path / "source-unavailable")
    assert resources.status()["available"]
    with pytest.raises(DiaryError): resources.sync()
    assert resources.status()["version"] == second["version"]
    (resources.root / second["version"] / "SKILL.md").write_text("edited", encoding="utf-8")
    with pytest.raises(DiaryError, match="修改"): resources.load()


def test_failed_style_pointer_commit_keeps_last_snapshot(tmp_path, monkeypatch):
    source = style_source(tmp_path)
    resources = StyleResources({"data_root": str(tmp_path / "data"), "zf_root": str(source)})
    before = resources.sync()
    (source / "SKILL.md").write_text("changed", encoding="utf-8")
    def fail(*args): raise OSError("disk full")
    monkeypatch.setattr("ai_workbench.e_diary.settings.atomic_json", fail)
    with pytest.raises(OSError): resources.sync()
    assert resources.status()["version"] == before["version"]
    assert resources.load()["SKILL.md"].startswith("original name")


def test_style_reference_escape_and_missing_dependency_preserve_old(tmp_path):
    source = style_source(tmp_path)
    resources = StyleResources({"data_root": str(tmp_path / "data"), "zf_root": str(source)})
    before = resources.sync()
    for reference in ("references/missing.md", "references/../../outside.md"):
        (source / "SKILL.md").write_text(reference, encoding="utf-8")
        with pytest.raises(DiaryError): resources.sync()
        assert resources.status()["version"] == before["version"]


def test_style_relative_reference_closure_and_rooted_manifest_rejection(tmp_path):
    source = style_source(tmp_path)
    (source / "references/voice.md").write_text('`rhythm.md`\n[rhythm](rhythm.md "Rhythm")', encoding="utf-8")
    (source / "references/rhythm.md").write_text("[recipe][r]\n\n[r]: ../prompts/write.md", encoding="utf-8")
    resources = StyleResources({"data_root": str(tmp_path / "data"), "zf_root": str(source)})
    current = resources.sync()
    assert resources.load()["references/rhythm.md"].startswith("[recipe]")
    current["files"]["\\outside.md"] = "x"
    with pytest.raises(DiaryError, match="路径"):
        resources._read(current)
    (source / "SKILL.md").write_text("`references/private-corpus.md`", encoding="utf-8")
    (source / "references/private-corpus.md").write_text("private", encoding="utf-8")
    with pytest.raises(DiaryError, match="原始语料"):
        resources.sync()


def test_style_preferences_manual_sync_and_failure_status(tmp_path, qt_app):
    from ai_workbench.e_diary.pages import Preferences
    source = style_source(tmp_path)
    config = {"data_root": str(tmp_path / "data"), "zf_root": str(source)}
    settings = Settings(config["data_root"], config)
    page = Preferences(settings, config, lambda _: None)
    assert "尚未同步" in page.style_status.text()
    QTest.mouseClick(page.sync_style_button, Qt.LeftButton)
    assert "上次同步" in page.style_status.text()
    old = page.style.status()["version"]
    (source / "SKILL.md").write_text("references/missing.md", encoding="utf-8")
    QTest.mouseClick(page.sync_style_button, Qt.LeftButton)
    assert "同步失败" in page.message.text()
    assert page.style.status()["version"] == old
    page.close()


def directory_fixture(tmp_path):
    root = tmp_path / "laboratory"
    root.mkdir()
    (root / "notes.md").write_text("之前的实验背景", encoding="utf-8")
    settings = Settings(tmp_path / "data")
    library = DiaryLibrary(tmp_path / "data")
    sources = Sources(settings, library, {"read_codex": False})
    sources.register([{"id": "lab", "path": str(root), "enabled": True, "type": "directory"}])
    request = {"kind": "work", "start": "2026-10-01T00:00:00+08:00", "end": "2026-10-15T00:00:00+08:00"}
    return root, settings, library, sources, request


def test_directory_registration_changes_comparison_and_durable_coverage(tmp_path):
    root, settings, library, sources, request = directory_fixture(tmp_path)
    collect = lambda: sources.collect(request, threading.Event(), lambda _: None)
    initial = collect()
    assert initial["documents"][0]["evidence_role"] == "historical_background"
    assert not initial["directory_versions"]["lab"]["files"]
    (root / "notes.md").write_text("补充的早期实验结果", encoding="utf-8")
    changed = collect()
    assert changed["documents"][0]["evidence_role"] == "delayed_evidence"
    sources.acknowledge(changed, {**request, "comparison": True})
    assert collect()["directory_versions"]["lab"]["files"]
    sources.acknowledge(changed, request)
    assert not collect()["directory_versions"]["lab"]["files"]
    reopened = Sources(Settings(library.root), library, {"read_codex": False})
    assert not reopened.collect(request, threading.Event(), lambda _: None)["directory_versions"]["lab"]["files"]
    sources.register([{k: v for k, v in settings.data["sources"][0].items() if k in ("id", "path", "type", "enabled")}])
    assert not collect()["directory_versions"]["lab"]["files"]


def test_pptx_directory_text_and_corrupt_or_entity_xml_are_bounded(tmp_path):
    root, settings, library, sources, request = directory_fixture(tmp_path)
    with zipfile.ZipFile(root / "slides.pptx", "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", '<a:r xmlns:a="urn:a"><a:t>实验已经跑通</a:t></a:r>')
    data = sources.collect(request, threading.Event(), lambda _: None)
    assert any("实验已经跑通" in doc["body"] for doc in data["documents"])
    for encoding in ("utf-8", "utf-16", "utf-32"):
        with zipfile.ZipFile(root / "bad.pptx", "w") as archive:
            archive.writestr("ppt/slides/slide1.xml", '<!DOCTYPE t [<!ENTITY x "bad">]><t>&x;</t>'.encode(encoding))
        data = sources.collect(request, threading.Event(), lambda _: None)
        assert any("DTD" in warning for warning in data["warnings"])
        assert "bad.pptx" not in data["directory_versions"]["lab"]["files"]
    (root / "bad.pptx").write_bytes(b"not a zip")
    assert any("bad.pptx" in warning for warning in sources.collect(request, threading.Event(), lambda _: None)["warnings"])
    cancelled = threading.Event(); cancelled.set()
    with pytest.raises(DiaryError, match="取消"):
        sources.collect(request, cancelled, lambda _: None)


def test_lab_priority_history_and_adopted_versions_budget(tmp_path, monkeypatch):
    root, settings, library, sources, request = directory_fixture(tmp_path)
    library.save(fields(date="2026-09-20", body="长期想让实验过程更可靠"))
    library.save(fields(kind="work", date="2026-09-21", body="过去的生成报告"))
    for index in range(5):
        (root / f"experiment-{index}.md").write_text("新增实验材料" * 2000, encoding="utf-8")
    sources.config["read_codex"] = True
    monkeypatch.setattr(sources, "_sessions", lambda *args: [{"id": "huge", "body": "x"*180000, "origin": "codex"}])
    sources.session_warnings = []
    data = sources.collect(request, threading.Event(), lambda _: None)
    assert any(doc["origin"] == "directory" for doc in data["documents"])
    assert any(doc["origin"] == "diary" and doc["evidence_role"] == "historical_background" for doc in data["documents"])
    assert any("4 万" in warning for warning in data["warnings"])
    adopted = data["directory_versions"]["lab"]["files"]
    assert 0 < len(adopted) < 5
    sources.acknowledge(data, request)
    assert set(adopted) == set(settings.data["sources"][0]["covered"])
    assert not any(doc["origin"] == "directory" for doc in sources.collect({**request, "kind": "development"}, threading.Event(), lambda _: None)["documents"])


def test_generation_failure_cancel_and_comparison_do_not_consume_directory(tmp_path, qt_app, monkeypatch):
    root, settings, library, sources, request = directory_fixture(tmp_path)
    (root / "notes.md").write_text("后来补充的实验结果", encoding="utf-8")
    config = {"data_root": str(library.root), "staging_root": str(tmp_path / "scratch")}
    monkeypatch.setattr("ai_workbench.e_diary.jobs.style_resources", lambda *args: ("", {}))
    class Adapter:
        fail = False
        cancel = False
        def generate(self, prompt, directory, cancelled, progress):
            self.prompt = prompt
            if self.cancel: cancelled.set()
            if self.fail: raise DiaryError("controlled failure")
            return {"title": "一条主线", "body": "这段时间逐渐把实验思路理顺了。"}
    adapter = Adapter()
    jobs = GenerationJobs(adapter, sources, library, settings, Reports(settings), Cycles(settings), config)
    for mode in ("fail", "cancel", "comparison", "normal"):
        adapter.fail, adapter.cancel = mode == "fail", mode == "cancel"
        jobs.submit({**request, "comparison": mode == "comparison"})
        until(qt_app, lambda: not jobs.state["pending"])
        assert bool(settings.data["sources"][0]["covered"]) == (mode == "normal")
    assert "600–2000" in adapter.prompt and "historical_background" in adapter.prompt
    assert len(library.query(kind="work")) == 2
    assert settings.data["cycles"]["work"]["last_end"] is None


def test_truncated_directory_version_remains_pending(tmp_path):
    root, settings, library, sources, request = directory_fixture(tmp_path)
    (root / "notes.md").write_text("背景" * 9000 + "新增结果", encoding="utf-8")
    bundle = sources.collect(request, threading.Event(), lambda _: None)
    assert any(doc["origin"] == "directory" and not doc["complete"] for doc in bundle["documents"])
    sources.acknowledge(bundle, request)
    assert not settings.data["sources"][0]["covered"]
    assert any("未推进该文件覆盖" in value for value in bundle["warnings"])


def test_saved_generation_recovers_coverage_without_regenerating(tmp_path, qt_app, monkeypatch):
    root, settings, library, sources, request = directory_fixture(tmp_path)
    (root / "notes.md").write_text("新增实验进展", encoding="utf-8")
    monkeypatch.setattr("ai_workbench.e_diary.jobs.style_resources", lambda *args: ("", {}))
    class Adapter:
        calls = 0
        def generate(self, *args):
            self.calls += 1
            return {"title": "已保存的主线", "body": "实验思路有了进展。"}
    adapter = Adapter()
    config = {"staging_root": str(tmp_path / "scratch")}
    cycles = Cycles(settings)
    jobs = GenerationJobs(adapter, sources, library, settings, Reports(settings), cycles, config)
    with monkeypatch.context() as patch:
        patch.setattr(sources, "acknowledge", lambda *args: (_ for _ in ()).throw(OSError("disk")))
        jobs.submit({**request, "automatic": True})
        until(qt_app, lambda: not jobs.state["pending"])
        assert jobs.state["error"] is None and "覆盖记录待恢复" in jobs.state["stage"]
        assert len(library.query(kind="work")) == 1 and "work" in cycles.blocked
        with pytest.raises(DiaryError, match="报告已保存"):
            jobs.submit({**request, "automatic": True})
    reopened = DiaryLibrary(library.root)
    recovered = GenerationJobs(adapter, sources, reopened, settings, Reports(settings), Cycles(settings), config)
    assert settings.data["sources"][0]["covered"]
    assert settings.data["cycles"]["work"]["last_end"] == request["end"]
    assert not reopened.query(kind="work")[0]["provenance"].get("pending_coverage")
    recovered.submit({**request, "automatic": True})
    assert adapter.calls == 1 and len(reopened.query(kind="work")) == 1
    recovered.cycles.blocked.add("work")
    with monkeypatch.context() as patch:
        patch.setattr(reopened, "acknowledge_generation", lambda *args: (_ for _ in ()).throw(OSError("descriptor")))
        recovered.submit({**request, "comparison": True})
        until(qt_app, lambda: not recovered.state["pending"])
        assert not reopened.read(recovered.state["entry_id"])["provenance"].get("pending_coverage")
    assert "work" in recovered.cycles.blocked


def test_demo_new_resource_entrypoints_do_not_read_private_paths(tmp_path, monkeypatch):
    config = {"demo": True, "data_root": str(tmp_path), "zf_root": str(tmp_path / "style")}
    def forbidden(*args, **kwargs):
        pytest.fail("demo accessed a private path")
    monkeypatch.setattr("ai_workbench.e_diary.settings.load_json", forbidden)
    monkeypatch.setattr("ai_workbench.e_diary.sources.os.scandir", forbidden)
    assert not StyleResources(config).status()["available"]
    sources = Sources(Settings(), DiaryLibrary(), config)
    with pytest.raises(DiaryError, match="演示模式"):
        sources.register([{"id": "private", "type": "directory", "path": str(tmp_path)}])


def test_comparison_ui_saves_first_and_preserves_original(qt_app, monkeypatch):
    window = create_window(demo=True)
    original = window.library.query(kind="work")[0]
    window.editor.load(original)
    sent = []
    monkeypatch.setattr(window.jobs, "submit", lambda request: sent.append(request))
    monkeypatch.setattr(window.editor, "save", lambda: False)
    window.compare(original)
    assert not sent
    monkeypatch.setattr(window.editor, "save", lambda: True)
    window.compare(original)
    assert sent[0]["comparison"] and sent[0]["comparison_of"] == original["id"]
    assert "entry_id" not in sent[0]
    assert window.library.read(original["id"])["body"] == original["body"]
    window.editor.clear()
    assert window.editor.comparison.isHidden()
    window.close()


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


def test_empty_section_clears_previous_body_and_record_actions(qt_app):
    window = create_window(demo=True)
    assert window.editor.body.toPlainText()
    for entry in window.library.query(kind="work"):
        window.library.delete(entry["id"])
    window.navigate("work")
    editor = window.editor
    assert editor.record is None and editor.body.toPlainText() == ""
    assert editor.title.text() == "" and editor.preview.toPlainText() == ""
    assert editor.chart is None and editor.status.text() == "暂无记录"
    assert all(widget.isHidden() for widget in (editor.generated_label, editor.regen, editor.sources, editor.restore))
    window.new_entry()
    assert editor.isEnabled() and not editor.preview_button.isHidden()
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
    # This test owns late transport events; capability policy has dedicated tests.
    monkeypatch.setattr("ai_workbench.e_diary.codex.isolation.exec_command", lambda *a, **k: ["synthetic-codex"])
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


# Startup catch-up, using the real scheduler and controlled generation.
AT = datetime.fromisoformat("2026-11-05T14:00:00+08:00")
ANCHOR = "2026-10-14T09:00:00+08:00"


class CycleClock(datetime):
    """Freeze local wall time too, independently of the CI host timezone."""
    instant = AT

    @classmethod
    def now(cls, tz=None):
        value = cls.fromisoformat(cls.instant.isoformat())
        return value.astimezone(tz) if tz is not None else value

    def astimezone(self, tz=None):
        return self if tz is None else super().astimezone(tz)


def until(app, condition, seconds=3):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert condition()


@pytest.fixture
def catchup(qt_app, tmp_path, monkeypatch):
    import ai_workbench.e_diary.cycles as module

    monkeypatch.setattr(module, "datetime", CycleClock)
    monkeypatch.setattr("ai_workbench.e_diary.jobs.style_resources", lambda *args: ("", {}))

    class Generation:
        def __init__(self):
            self.requests = []
            self.fail = set()
            self.hold = set()
            self.release = threading.Event()

        def collect(self, request, cancelled, progress):
            self.requests.append(deepcopy(request))
            return {"start": request["start"], "end": request["end"],
                    "documents": [{"id": "fixture", "origin": "fixture", "body": "有日期的测试材料"}],
                    "warnings": []}

        def generate(self, prompt, directory, cancelled, progress):
            kind = self.requests[-1]["kind"]
            progress("测试正文生成中")
            while kind in self.hold and not self.release.wait(.005):
                if cancelled.is_set():
                    raise DiaryError("任务已取消")
            if kind in self.fail:
                raise DiaryError(kind + " controlled failure")
            return {"title": kind + " 补做报告", "body": "独立测试资料生成的正文", "files": []}

    windows = []

    def make():
        root = tmp_path / "private-fixture"
        settings = Settings(root)
        if not settings.path.exists():
            rules = deepcopy(settings.data["cycles"])
            for rule in rules.values():
                rule["anchor"] = ANCHOR
            settings.update(cycles=rules)
        window = create_window({"data_root": str(root), "read_codex": False,
                                "staging_root": str(tmp_path / "scratch")})
        generation = Generation()
        window.sources.collect = generation.collect
        window.jobs.adapter = generation
        windows.append(window)
        return window, generation

    yield make
    for window in windows:
        window.close()
        until(qt_app, lambda: not window.jobs.state["pending"])
        window.close()
        window.deleteLater()
    qt_app.processEvents()


def test_overview_and_due_share_time_merge_and_blocking():
    settings = Settings()
    for rule in settings.data["cycles"].values():
        rule["anchor"] = ANCHOR
    cycles = Cycles(settings)
    before = datetime.fromisoformat("2026-10-21T08:59:59+08:00")
    assert cycles.due(before) is None
    assert cycles.overview(before)[0]["next_due"] == "2026-10-21T09:00:00+08:00"
    at = datetime.fromisoformat("2026-10-23T14:00:00+08:00")
    request = cycles.due(at)
    assert request == cycles.overview(at)[0]["request"]
    assert request["start"] == ANCHOR
    assert request["end"] == "2026-10-23T09:00:00+08:00"
    cycles.completed(request, False)
    assert cycles.overview(at)[0]["blocked"]
    assert cycles.due(at)["kind"] == "work"
    assert cycles.retry("development", at) == request
    cycles.completed(request, True)
    assert cycles.overview(at)[0]["next_due"] == "2026-10-30T09:00:00+08:00"
    assert cycles.overview(AT)[0]["request"]["start"] == request["end"]


def test_startup_drains_all_types_without_timer_delay_and_reopen_does_not_repeat(qt_app, catchup):
    window, generation = catchup()
    assert generation.requests == []  # Construction never starts model work synchronously.
    until(qt_app, lambda: len(window.library.query()) == 3 and not window.jobs.state["pending"])
    assert [r["kind"] for r in generation.requests] == ["development", "work", "personal"]
    for request in generation.requests:
        assert request["start"] == ANCHOR
        assert request["end"] == "2026-11-05T09:00:00+08:00"
    for _ in range(3):
        window.check_cycles()
        qt_app.processEvents()
    assert len(generation.requests) == 3
    assert window.cycles.due() is None
    window.close()
    reopened, second = catchup()
    qt_app.processEvents()
    reopened.check_cycles()
    assert second.requests == []
    assert len(reopened.library.query()) == 3


def test_pending_guards_and_typed_retry_survive_another_type_success(qt_app, catchup):
    window, generation = catchup()
    generation.fail.add("development")
    generation.hold.add("work")
    until(qt_app, lambda: len(generation.requests) == 2 and window.jobs.state["pending"])
    for _ in range(3):
        window.check_cycles()
    assert len(generation.requests) == 2
    assert not window.cycle_status.rows["development"]["retry"].isEnabled()
    assert not window.cycle_page.retry_buttons["development"].isEnabled()
    generation.release.set()
    until(qt_app, lambda: len(generation.requests) == 3 and not window.jobs.state["pending"])
    assert window.settings.data["cycles"]["development"]["last_end"] is None
    assert window.cycles.blocked == {"development"}
    assert "controlled failure" in window.cycle_status.rows["development"]["label"].text()
    generation.fail.clear()
    QTest.mouseClick(window.cycle_page.retry_buttons["development"], Qt.LeftButton)
    until(qt_app, lambda: len(window.library.query()) == 3 and not window.jobs.state["pending"])
    assert [r["kind"] for r in generation.requests] == ["development", "work", "personal", "development"]
    assert not window.cycles.blocked


def test_cancelled_type_retries_from_status_and_reopen_retries_failure(qt_app, catchup):
    window, generation = catchup()
    generation.hold.add("development")
    until(qt_app, lambda: len(generation.requests) == 1)
    window.jobs.cancel()
    until(qt_app, lambda: len(generation.requests) == 3 and not window.jobs.state["pending"])
    assert window.settings.data["cycles"]["development"]["last_end"] is None
    assert "取消" in window.cycle_status.rows["development"]["label"].text()
    generation.hold.clear()
    generation.fail.add("development")
    QTest.mouseClick(window.cycle_status.rows["development"]["retry"], Qt.LeftButton)
    until(qt_app, lambda: len(generation.requests) == 4 and not window.jobs.state["pending"])
    window.close()
    reopened, second = catchup()
    until(qt_app, lambda: len(reopened.library.query()) == 3 and not reopened.jobs.state["pending"])
    assert [r["kind"] for r in second.requests] == ["development"]


def test_status_is_global_preserves_editor_and_opens_exact_filtered_report(qt_app, catchup, monkeypatch):
    window, generation = catchup()
    window.show()
    window.new_entry()
    window.editor.body.setPlainText("自动补做期间继续写日记")
    until(qt_app, lambda: len(generation.requests) == 3 and not window.jobs.state["pending"])
    assert window.kind == "diary"
    assert window.editor.body.toPlainText() == "自动补做期间继续写日记"
    for page in ("sources", "cycles", "report", "settings", "diary"):
        window.navigate(page)
        assert window.cycle_status.isVisible()
    report = window.library.query(kind="work")[0]
    window.search.setText("无法匹配的筛选条件")
    window.month.setCurrentIndex(2)
    original_page = window.pages.currentWidget()
    original_filters = (window.search.text(), window.month.currentIndex())
    with monkeypatch.context() as patch:
        patch.setattr(window.editor, "save", lambda: False)
        QTest.mouseClick(window.cycle_status.rows["work"]["open"], Qt.LeftButton)
        assert window.pages.currentWidget() is original_page
        assert (window.search.text(), window.month.currentIndex()) == original_filters
    QTest.mouseClick(window.cycle_status.rows["work"]["open"], Qt.LeftButton)
    assert window.kind == "work"
    assert window.editor.record["id"] == report["id"]
    assert window.search.text() == "" and window.month.currentIndex() == 0
    assert window.list.currentItem().data(Qt.UserRole) == report["id"]


def test_close_before_first_event_does_not_start_catchup(qt_app, catchup):
    window, generation = catchup()
    window.close()
    qt_app.processEvents()
    assert generation.requests == []


def test_close_during_generation_cancels_without_starting_next_type(qt_app, catchup):
    window, generation = catchup()
    generation.hold.add("development")
    until(qt_app, lambda: len(generation.requests) == 1)
    window.close()
    until(qt_app, lambda: not window.jobs.state["pending"])
    qt_app.processEvents()
    assert [r["kind"] for r in generation.requests] == ["development"]
    assert window.settings.data["cycles"]["development"]["last_end"] is None


def test_manual_generation_does_not_replace_automatic_result_link(qt_app, catchup):
    window, generation = catchup()
    until(qt_app, lambda: len(generation.requests) == 3 and not window.jobs.state["pending"])
    result = deepcopy(window.cycle_status.results["work"])
    window.jobs.submit({"kind": "work", "start": ANCHOR, "end": AT.isoformat()})
    until(qt_app, lambda: not window.jobs.state["pending"])
    assert window.cycle_status.results["work"] == result


def test_later_failure_retains_previously_completed_report_link(qt_app, catchup, monkeypatch):
    window, generation = catchup()
    until(qt_app, lambda: len(generation.requests) == 3 and not window.jobs.state["pending"])
    completed_id = window.cycle_status.results["development"]["entry_id"]

    class Later(CycleClock):
        instant = AT + timedelta(days=8)

    monkeypatch.setattr("ai_workbench.e_diary.cycles.datetime", Later)
    generation.fail.add("development")
    window.check_cycles()
    until(qt_app, lambda: len(generation.requests) == 5 and not window.jobs.state["pending"])
    assert window.cycle_status.results["development"]["entry_id"] == completed_id
    assert not window.cycle_status.rows["development"]["open"].isHidden()
    assert not window.cycle_status.rows["development"]["retry"].isHidden()


@pytest.mark.parametrize("config", [{}, {"prose_path": ""}, {"prose_path": "   "}])
def test_default_prose_is_available_without_external_configuration(config):
    text, hashes = style_resources(config)
    assert "# Prose Discipline" in text
    assert "Concision is a consequence of relevance" in text
    assert len(hashes) == 1


def test_missing_custom_prose_does_not_silently_fall_back(tmp_path):
    with pytest.raises(DiaryError, match="写作资源缺失"):
        style_resources({"prose_path": str(tmp_path / "missing.md")})


def test_preferences_can_save_builtin_prose(qt_app, tmp_path):
    from ai_workbench.e_diary.pages import Preferences
    settings = Settings()
    config = {key: str(tmp_path / key) for key in ("codex_cli", "zf_root", "staging_root")}
    widget = Preferences(settings, config, lambda _: None)
    try:
        widget.fields["prose_path"].setText("")
        widget.save()
        assert settings.data["runtime"]["prose_path"] == ""
        assert "Prose Discipline" in style_resources(config)[0]
        widget.fields["prose_path"].setText("relative.md")
        widget.save()
        assert settings.data["runtime"]["prose_path"] == ""
        assert "绝对路径" in widget.message.text()
    finally:
        widget.close()
