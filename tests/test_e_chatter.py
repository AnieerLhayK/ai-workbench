"""Behavioral checks at the application/provider seam, with synthetic files only."""
import json
from pathlib import Path
import threading
import zipfile

import pytest

from ai_workbench.e_chatter.files import ChatterError, fingerprint, inside, skill_info, tree, write_tree
from ai_workbench.e_chatter.service import Service
from ai_workbench.e_chatter import migration
from ai_workbench.e_chatter.codex import reply_prefix, argv


FILES = {"SKILL.md": b"---\nname: sample\ndescription: Synthetic character for tests.\n---\n\nRead [voice](references/voice.md). Write original prose.\n", "references/voice.md": "保留事实，表达克制。".encode()}


@pytest.fixture
def service(tmp_path):
    result = Service(tmp_path / "data")
    yield result
    result.store.close()


def response(reply="test", **values):
    return dict(reply=reply, status="completed", files=[], diagnosis="", handoff="", build_intake="") | values


def role(service, session, kind):
    confirmation = service.prepare_engineering(session["id"], kind)
    return service.start_engineering(session["id"], kind, confirmation["token"])


def loaded(service):
    character = service.register(FILES)
    session = service.session()
    service.load_character(session["id"], character["id"])
    return session, character


def test_empty_install_and_nested_folders_persist_without_demo_characters(tmp_path):
    s = Service(tmp_path / "data")
    assert s.snapshot()["characters"] == []
    top = s.folder("写作")
    nested = s.folder("随笔", top["id"])
    session = s.session("讨论", nested["id"])
    s.folder("随笔", top["id"], nested["id"], True)
    s.settings(theme="dark")
    s.store.close()
    reopened = Service(tmp_path / "data")
    assert reopened.store.get("sessions", session["id"])["folder"] == nested["id"]
    assert reopened.store.get("folders", nested["id"])["collapsed"]
    assert reopened.store.setting("theme") == "dark"
    with pytest.raises(ChatterError):
        reopened.folder("写作", nested["id"], top["id"])
    reopened.store.close()


def test_registration_requires_user_classification_and_valid_references(service, tmp_path):
    source = tmp_path / "original"
    write_tree(source, FILES)
    original = fingerprint(tree(source))
    with pytest.raises(ChatterError):
        service.import_character(source)
    character = service.import_character(source, "runtime", True)
    assert character["category"] == "runtime"
    assert fingerprint(service.character_files(character["id"])) == original
    assert fingerprint(tree(source)) == original
    with pytest.raises(ChatterError, match="引用文件缺失"):
        skill_info({"SKILL.md": FILES["SKILL.md"]})
    with pytest.raises(ChatterError):
        service.register(FILES, "general")


def test_engineering_confirmation_is_bound_single_use_and_text_uses_same_gate(service):
    session, _ = loaded(service)
    other = service.session()
    token = service.prepare_engineering(session["id"], "maintainer")["token"]
    with pytest.raises(ChatterError):
        service.start_engineering(other["id"], "maintainer", token)
    assert "confirmation_required" in service.prepare_request(session["id"], "$maintainer 请检查")
    assert not service.store.rows("tasks")
    task = role(service, session, "maintainer")
    with pytest.raises(ChatterError):
        service.start_engineering(session["id"], "maintainer", token)
    assert task["status"] == "needs_input"


def test_staged_review_keeps_original_and_old_version_immutable(service, tmp_path):
    source = tmp_path / "original"
    write_tree(source, FILES)
    original = fingerprint(tree(source))
    character = service.import_character(source, confirmed_character=True)
    session = service.session()
    service.load_character(session["id"], character["id"])
    task = role(service, session, "maintainer")
    request = service.prepare_request(session["id"], "只调整语气", task["id"])
    service.complete(request, response(files=[{"path": "references/voice.md", "content": "用细节呈现情绪，保留事实。"}]))
    proposal = service.store.rows("proposals")[0]
    assert service.store.get("characters", character["id"])["version"] == 1
    service.accept(proposal["id"])
    assert service.store.get("characters", character["id"])["version"] == 2
    assert service.character_files(character["id"], 1) == FILES
    assert fingerprint(tree(source)) == original
    assert service.store.get("sessions", session["id"])["version"] == 1
    with pytest.raises(ChatterError):
        service.accept(proposal["id"])


def test_stale_and_tampered_proposals_cannot_overwrite_current_version(service):
    session, character = loaded(service)
    task = role(service, session, "maintainer")
    request = service.prepare_request(session["id"], "维护角色", task["id"])
    service.complete(request, response(files=[{"path": "references/voice.md", "content": "新版本"}]))
    proposal = service.store.rows("proposals")[0]
    Path(proposal["path"], "references/voice.md").write_text("外部修改", encoding="utf-8")
    with pytest.raises(ChatterError, match="副本发生变化"):
        service.accept(proposal["id"])
    assert service.store.get("characters", character["id"])["version"] == 1


def test_cancelled_completion_does_not_publish_messages_or_files(service):
    session, _ = loaded(service)
    request = service.prepare_request(session["id"], "你好")
    service.cancel_task(request["task_id"])
    assert service.complete(request, response("late")) is None
    assert not any(m["text"] == "late" for m in service.store.rows("messages"))


def test_switch_warns_but_allows_explicit_continue_and_new_session(service):
    session, first = loaded(service)
    second = service.register(FILES)
    assert "warning" in service.load_character(session["id"], second["id"])
    assert service.store.get("sessions", session["id"])["character_id"] == first["id"]
    service.load_character(session["id"], second["id"], choice="continue")
    result = service.load_character(session["id"], first["id"], choice="new")
    assert result["session_id"] != session["id"]


def test_engineering_history_is_isolated_then_returns_to_character(service):
    session, _ = loaded(service)
    request = service.prepare_request(session["id"], "聊天内容")
    service.complete(request, response("角色回复"))
    task = role(service, session, "generator")
    request = service.prepare_request(session["id"], "创建新角色", task["id"])
    assert request["payload"]["history"] == []
    service.complete(request, response("还需要材料", status="needs_input"))
    followup = service.prepare_request(session["id"], "补充材料")
    assert followup["payload"]["role"] == "generator"
    assert any(m["text"] == "还需要材料" for m in followup["payload"]["history"])
    service.complete(followup, response("任务结束"))
    normal = service.prepare_request(session["id"], "继续聊天")
    assert normal["payload"]["role"] == "chat"
    assert all(m["text"] not in ("任务结束", "还需要材料") for m in normal["payload"]["history"])


def test_doctor_uses_selected_output_version_and_saves_linkable_records(service):
    session, first = loaded(service)
    request = service.prepare_request(session["id"], "你好")
    service.complete(request, response("角色一的回复"))
    message = service.store.rows("messages")[-1]
    second = service.register(FILES)
    service.load_character(session["id"], second["id"], choice="continue")
    task = service.doctor(session["id"], message["id"])
    assert task["character_id"] == first["id"]
    request = service.prepare_request(session["id"], "诊断", task["id"])
    assert request["payload"]["target"]["id"] == message["id"]
    service.complete(request, response(diagnosis="# 有依据的诊断", handoff="# 需要维护"))
    records = service.store.rows("records")
    assert len(records) == 2
    assert all(r["target_message_id"] == message["id"] and Path(r["path"]).is_file() for r in records)
    with pytest.raises(ChatterError):
        service.doctor(service.session()["id"])


def test_doctor_cannot_stage_files_and_normal_chat_cannot_write_arbitrary_documents(service):
    session, _ = loaded(service)
    request = service.prepare_request(session["id"], "你好")
    service.complete(request, response())
    task = service.doctor(session["id"])
    request = service.prepare_request(session["id"], "诊断", task["id"])
    with pytest.raises(ChatterError):
        service.complete(request, response(files=[{"path": "SKILL.md", "content": "bad"}]))
    assert not service.store.rows("proposals")


@pytest.mark.parametrize("instruction", ["请润色这份文稿", "Please rewrite the attached draft", "再简洁一点"])
def test_ordinary_document_edits_use_only_explicit_copies(service, tmp_path, instruction):
    source = tmp_path / "draft.md"
    source.write_text("原文", encoding="utf-8")
    material = service.attach(source)
    session = service.session()
    request = service.prepare_request(session["id"], instruction, material_ids=[material["id"]])
    service.complete(request, response(files=[{"path": "draft.md", "content": "副本正文"}]))
    proposal = service.store.rows("proposals")[0]
    service.accept(proposal["id"])
    assert source.read_text(encoding="utf-8") == "原文"
    assert (service.root / "documents" / proposal["id"] / "draft.md").read_text(encoding="utf-8") == "副本正文"


def test_external_skill_path_is_temporary_and_cannot_register_itself(service, tmp_path):
    source = tmp_path / "foreign"
    write_tree(source, FILES)
    session = service.session()
    request = service.prepare_request(session["id"], f'@"{source / "SKILL.md"}" 帮我写作')
    assert len(request["payload"]["materials"]) == 1
    assert service.snapshot()["characters"] == []


@pytest.mark.parametrize("name", ["../source.md", "C:" + "/other.md", "/tmp/other.md", "folder/../../x", "NUL", "a:stream"])
def test_staging_paths_cannot_escape(tmp_path, name):
    with pytest.raises(ChatterError):
        inside(tmp_path, name)


def test_migration_merges_without_overwrite_and_excludes_credentials_staging(service, tmp_path):
    session, _ = loaded(service)
    request = service.prepare_request(session["id"], "你好")
    service.complete(request, response("保存的消息"))
    private = service.root / "staging/provider/auth.json"
    private.parent.mkdir(parents=True)
    private.write_text('"not-a-real-secret"')
    path = tmp_path / "library.zip"
    migration.export_package(service, path)
    with zipfile.ZipFile(path) as archive:
        assert not any("staging" in name or "auth" in name or ".sqlite" in name for name in archive.namelist())
    other = Service(tmp_path / "other")
    existing = other.session("已有会话")
    preview = migration.preview_package(other, path)
    assert preview["sessions"] == 1
    migration.import_package(other, preview["token"])
    assert other.store.get("sessions", existing["id"])["title"] == "已有会话"
    assert len(other.snapshot()["characters"]) == 1
    imported = next(s for s in other.snapshot()["sessions"] if s["id"] != existing["id"])
    assert imported["character_id"] != session.get("character_id")
    assert other.character_files(imported["character_id"]) == FILES
    assert any(m["text"] == "保存的消息" and m["session_id"] == imported["id"] for m in other.snapshot()["messages"])
    other.store.close()


def test_malformed_migration_does_not_change_library(service, tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../escape", "bad")
    before = service.snapshot()
    with pytest.raises(ChatterError):
        migration.preview_package(service, path)
    assert service.snapshot() == before


def test_bundled_builder_writes_source_readme_only_in_staging(service, tmp_path):
    from ai_workbench.e_chatter import builder
    source = tmp_path / "authorized.txt"
    source.write_text("窗外下着雨。我把桌上的书翻到上次停下的那页，读了一小段。\n" * 30, encoding="utf-8")
    before = source.read_bytes()
    material = service.attach(source)
    session = service.session()
    task = role(service, session, "generator")
    request = service.prepare_request(session["id"], "生成角色", task["id"], [material["id"]])
    intake = dict(character_id="test-character", display_name="Test Character", target_tasks=["discussion"], authorization_confirmed=True,
                  privacy_boundary_accepted=True, material_ids=[material["id"]], output_path=str(tmp_path / "should-not-exist"))
    directory = builder.prepare(service, request, json.dumps(intake))
    builder.worker(directory)
    assert (directory / "receipt.json").is_file()
    assert (directory / "materials" / material["id"] / "README.md").is_file()
    assert source.read_bytes() == before
    assert not (tmp_path / "README.md").exists()
    assert not (tmp_path / "should-not-exist").exists()


def test_reply_stream_never_exposes_proposals_or_incomplete_json():
    assert reply_prefix('{"reply":"你好\\n世') == "你好\n世"
    assert reply_prefix('{"reply":"你好","files":[{"path":"private"') == "你好"


def test_demo_is_memory_only_and_refuses_real_paths(tmp_path):
    s = Service()
    s.seed_demo()
    assert s.snapshot()["demo"] and len(s.snapshot()["characters"]) == 2
    with pytest.raises(ChatterError):
        s.attach(tmp_path / "anything.md")
    with pytest.raises(ChatterError):
        s.refresh_characters()
    s.store.close()


def test_engineering_retains_attached_material_between_turns(service, tmp_path):
    source = tmp_path / "draft.txt"
    source.write_text("Synthetic authorized writing", encoding="utf-8")
    material = service.attach(source)
    session = service.session()
    task = role(service, session, "generator")
    first = service.prepare_request(session["id"], "请先询问目标", task["id"], [material["id"]])
    service.complete(first, response(status="needs_input"))
    second = service.prepare_request(session["id"], "用于随笔写作")
    assert second["materials"][0]["text"] == source.read_text()
    assert second["task_id"] == task["id"]


def test_engineering_materials_survive_restart_without_reopening_source(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Authorized original material")
    root = tmp_path / "library"
    first = Service(root)
    session = first.session()
    task = role(first, session, "generator")
    material = first.attach(source)
    request = first.prepare_request(session["id"], "先询问", task["id"], [material["id"]])
    first.complete(request, response(status="needs_input"))
    first.store.close()
    source.unlink()  # original is no longer needed; the authorized copy is durable
    second = Service(root)
    try:
        followup = second.prepare_request(session["id"], "继续")
        assert followup["materials"][0]["text"] == "Authorized original material"
    finally:
        second.store.close()


def test_doctor_reentry_leaves_no_pending_task(service):
    session, _ = loaded(service)
    request = service.prepare_request(session["id"], "第一条")
    service.complete(request, response())
    running = service.prepare_request(session["id"], "正在生成")
    before = len(service.snapshot()["tasks"])
    with pytest.raises(ChatterError):
        service.doctor(session["id"])
    assert len(service.snapshot()["tasks"]) == before
    service.complete(running, response())
    assert service.prepare_request(session["id"], "继续聊天")["payload"]["role"] == "chat"


def test_explicit_provisional_diagnosis_never_claims_character_evidence(service, tmp_path):
    session = service.session()
    request = service.prepare_request(session["id"], '@doctor --provisional 测试文字提到 @generator 与 @maintainer，还有 @"/unreadable/SKILL.md"')
    assert request["payload"]["character_context"]["status"] == "provisional"
    service.complete(request, response(diagnosis="临时分析"))
    record = service.snapshot()["records"][0]
    assert record["status"] == "provisional" and record["character_id"] is None
    assert record["body"].startswith("> Provisional")
    archive = tmp_path / "provisional.zip"
    migration.export_package(service, archive)
    assert migration.preview_package(service, archive)["records"] == 1


def test_completed_engineering_task_cannot_bypass_confirmation(service):
    session = service.session()
    task = role(service, session, "generator")
    request = service.prepare_request(session["id"], "开始", task["id"])
    service.complete(request, response())
    with pytest.raises(ChatterError):
        service.prepare_request(session["id"], "再创建", task["id"])


def test_root_skill_file_reference_requires_same_confirmation(service, tmp_path):
    path = tmp_path / "external" / "SKILL.md"
    path.parent.mkdir()
    path.write_text("---\nname: character-maintainer\ndescription: Engineering.\n---\n\nAdjust a character copy.")
    session = service.session()
    result = service.prepare_request(session["id"], '@"' + str(path) + '"')
    assert result["confirmation_required"]["role"] == "maintainer"
    assert not any(t["status"] == "running" for t in service.snapshot()["tasks"])


def test_migration_rejects_record_path_type_before_any_write(service, tmp_path):
    session, character = loaded(service)
    request = service.prepare_request(session["id"], "写一句话")
    service.complete(request, response())
    task = service.doctor(session["id"])
    request = service.prepare_request(session["id"], "诊断", task["id"])
    service.complete(request, response(diagnosis="A diagnosis"))
    valid = tmp_path / "valid.zip"
    migration.export_package(service, valid)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(valid) as source, zipfile.ZipFile(bad, "w") as target:
        for name in source.namelist():
            value = source.read(name)
            if name == "library.json":
                data = json.loads(value)
                data["data"]["records"][0]["kind"] = "../../outside"
                value = json.dumps(data).encode()
            target.writestr(name, value)
    before = service.snapshot()
    with pytest.raises(ChatterError):
        migration.preview_package(service, bad)
    assert service.snapshot() == before


def test_saved_document_review_contains_original_and_save_failure_keeps_version(service, tmp_path, monkeypatch):
    import ai_workbench.e_chatter.service as module
    source = tmp_path / "draft.md"
    source.write_text("原来的文字", encoding="utf-8")
    material = service.attach(source)
    session = service.session()
    request = service.prepare_request(session["id"], "请修改文稿", material_ids=[material["id"]])
    service.complete(request, response(files=[{"path": "draft.md", "content": "修改后的文字"}]))
    proposal = service.snapshot()["proposals"][0]
    assert proposal["changes"]["draft.md"]["before"] == "原来的文字"
    def fail(*args, **kwargs):
        raise OSError("simulated full disk")
    monkeypatch.setattr(module, "write_tree", fail)
    with pytest.raises(OSError):
        service.accept(proposal["id"])
    assert service.store.get("proposals", proposal["id"])["status"] == "pending"
    assert source.read_text(encoding="utf-8") == "原来的文字"
