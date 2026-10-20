"""Inspectable, credential-free migration; collisions never replace local rows."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import zipfile

from .files import ChatterError, atomic, fingerprint, inside, plain_path, relative, tree, uid, write_tree
from .store import TABLES


def export_package(service, destination):
    if not service.root:
        raise ChatterError("演示模式不导出本机资料")
    snapshot = service.snapshot()
    payload = {kind: snapshot[kind] for kind in TABLES}
    payload["settings"] = {k: snapshot["settings"].get(k) for k in ("theme", "model")}
    # Staged proposals and temporary inputs are intentionally not migrated.
    payload["proposals"] = [p for p in payload["proposals"] if p["status"] == "accepted"]
    for character in payload["characters"]:
        character["source"] = "迁移包"
    for session in payload["sessions"]:
        session.pop("authorized_agents", None)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for version in payload["versions"]:
            files = service.character_files(version["character_id"], version["number"])
            prefix = f"characters/{version['character_id']}/{version['id']}"
            for name, value in files.items():
                archive.writestr(prefix + "/" + name, value)
            version["path"] = prefix
        for proposal in payload["proposals"]:
            proposal["path"] = ""
        for record in payload["records"]:
            record["path"] = ""
        documents = service.root / "documents"
        if documents.exists():
            for name, value in tree(documents).items():
                archive.writestr("documents/" + name, value)
        archive.writestr("library.json", json.dumps({"schema": 1, "data": payload}, ensure_ascii=False))
    atomic(Path(destination), buffer.getvalue())
    return {"path": str(destination), "sessions": len(payload["sessions"]), "characters": len(payload["characters"])}


def preview_package(service, source):
    if not service.root:
        raise ChatterError("演示模式不读取迁移包")
    source = plain_path(Path(source))
    try:
        with zipfile.ZipFile(source) as archive:
            if sum(i.file_size for i in archive.infolist()) > 256 * 1024 * 1024 or len(archive.infolist()) > 16384:
                raise ChatterError("迁移包过大")
            names = [relative(i.filename) for i in archive.infolist()]
            if len(set(names)) != len(names) or any(n != "library.json" and not n.startswith(("characters/", "documents/")) for n in names):
                raise ChatterError("迁移包文件清单无效")
            document = json.loads(archive.read("library.json"))
            if document.get("schema") != 1 or not isinstance(document.get("data"), dict):
                raise ChatterError("迁移包版本不支持")
            data = document["data"]
            identifiers = set()
            for kind in TABLES:
                if not isinstance(data.get(kind), list):
                    raise ChatterError("迁移包记录不完整")
                for record in data[kind]:
                    if not isinstance(record, dict) or not isinstance(record.get("id"), str) or record["id"] in identifiers:
                        raise ChatterError("迁移包包含重复或无效标识")
                    identifiers.add(record["id"])
            files = {name: archive.read(name) for name in names if name != "library.json"}
            for version in data["versions"]:
                prefix = f"characters/{version['character_id']}/{version['id']}/"
                contents = {name[len(prefix):]: content for name, content in files.items() if name.startswith(prefix)}
                if fingerprint(contents) != version["hash"]:
                    raise ChatterError("迁移包角色文件校验失败")
            folder_ids = {r["id"] for r in data["folders"]}
            session_ids = {r["id"] for r in data["sessions"]}
            character_ids = {r["id"] for r in data["characters"]}
            task_ids = {r["id"] for r in data["tasks"]}
            message_ids = {r["id"] for r in data["messages"]}
            for record in data["records"]:
                if record.get("kind") not in ("diagnosis", "handoff") or not isinstance(record.get("body"), str):
                    raise ChatterError("迁移包诊断类型无效")
                provisional = record.get("status") == "provisional" and record.get("target_message_id") is None and record.get("character_id") is None
                if record.get("task_id") not in task_ids or (not provisional and record.get("target_message_id") not in message_ids):
                    raise ChatterError("迁移包诊断关联不完整")
            for task in data["tasks"]:
                if task.get("kind") not in ("chat", "generator", "maintainer", "doctor") or task.get("session_id") not in session_ids:
                    raise ChatterError("迁移包任务无效")
            for version in data["versions"]:
                if version.get("character_id") not in character_ids or type(version.get("number")) is not int or version["number"] < 1:
                    raise ChatterError("迁移包角色版本无效")
            for character in data["characters"]:
                if character.get("category") not in ("developing", "runtime") or not any(v["character_id"] == character["id"] and v["number"] == character.get("version") for v in data["versions"]):
                    raise ChatterError("迁移包角色登记无效")
            for session in data["sessions"]:
                if (session.get("folder") and session["folder"] not in folder_ids) or (session.get("character_id") and session["character_id"] not in character_ids):
                    raise ChatterError("迁移包会话关联不完整")
            if any(m.get("session_id") not in session_ids for m in data["messages"]):
                raise ChatterError("迁移包消息关联不完整")
            for folder in data["folders"]:
                seen, current = set(), folder
                while current.get("parent"):
                    if current["id"] in seen or current["parent"] not in folder_ids:
                        raise ChatterError("迁移包分类关系无效")
                    seen.add(current["id"])
                    current = next(f for f in data["folders"] if f["id"] == current["parent"])
    except (ValueError, KeyError, zipfile.BadZipFile, OSError) as error:
        if isinstance(error, ChatterError):
            raise
        raise ChatterError("无法读取迁移包，未修改本机资料") from error
    token = uid()
    service.previews[token] = (data, files)
    return {"token": token, "sessions": len(data["sessions"]), "characters": len(data["characters"]),
            "records": len(data["records"]), "note": "导入为独立记录，不覆盖本机已有内容；不包含登录信息与 staging。"}


def import_package(service, token):
    if token not in service.previews:
        raise ChatterError("请先预览迁移包")
    data, files = service.previews.pop(token)
    mapping = {row["id"]: uid() for kind in TABLES for row in data[kind]}

    def remap(value):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        return value

    with service.store.transaction():
        for kind in TABLES:
            for old in data[kind]:
                row = remap(old)
                if kind == "sessions":
                    row.pop("authorized_agents", None)
                    row.setdefault("model_preferences", {"codex": {"model": row.get("model") or data.get("settings", {}).get("model"), "effort": None}})
                if kind == "versions":
                    prefix = f"characters/{old['character_id']}/{old['id']}/"
                    contents = {name[len(prefix):]: value for name, value in files.items() if name.startswith(prefix)}
                    path = Path(service.store.setting("characters_root")) / row["character_id"] / (f"v{row['number']}-" + row["id"][:8])
                    write_tree(path, contents)
                    row["path"] = str(path)
                if kind == "tasks" and row["status"] in ("running", "needs_input"):
                    row.update(status="interrupted", error="迁移后可重新启动工程任务")
                if kind == "records":
                    path = inside(service.root, "records/" + row["kind"] + "/" + row["id"] + ".md")
                    atomic(path, ("---\n" + json.dumps({k: v for k, v in row.items() if k not in ("body", "path")}, ensure_ascii=False) + "\n---\n\n" + row["body"]).encode())
                    row["path"] = str(path)
                row.pop("provider_thread_id", None)
                service.store.add(kind, **row)
        for name, value in files.items():
            if name.startswith("documents/"):
                parts = name.split("/")
                parts[1] = mapping.get(parts[1], uid())
                atomic(inside(service.root, "/".join(parts)), value)
    return service.snapshot()
