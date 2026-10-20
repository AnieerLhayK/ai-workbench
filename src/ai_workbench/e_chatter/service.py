"""Application authority and test seam, independent of Qt and the model client."""
from __future__ import annotations

import json
from pathlib import Path
import re
from copy import deepcopy
from functools import wraps

from .files import ChatterError, atomic, digest, fingerprint, inside, plain_path, relative, skill_info, texts, tree, uid, write_tree
from .store import Store, now
from . import VERSION


ROLES = ("generator", "maintainer", "doctor")
CONFIRMATIONS = {"generator": "根据你提供的材料创建新的角色 skill。", "maintainer": "根据诊断和反馈调整角色副本，原始文件保持不变。"}


def locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.store.lock:
            return method(self, *args, **kwargs)
    return call


class Service:
    def __init__(self, root=None):
        self.store = Store(Path(root) if root else None)
        self.root = self.store.root
        self.memory_files = {}
        self.confirmations = {}
        self.materials = {}
        self.previews = {}
        # Upgrade preferences once; never infer old messages' execution metadata.
        with self.store.transaction():
            if not self.store.setting("agent"):
                self.store.put_setting("agent", "codex")
            for session in self.store.rows("sessions"):
                if "model_preferences" not in session:
                    self.store.update("sessions", session["id"], model_preferences={"codex": {"model": session.get("model") or self.store.setting("model"), "effort": None}})
        if self.root:
            plain_path(Path(self.store.setting("characters_root"))).mkdir(parents=True, exist_ok=True)
            for task in self.store.rows("tasks"):
                if task["status"] != "needs_input" or not task.get("material_ids"):
                    continue
                try:
                    content = inside(self.root / "staging", task["id"] + "/materials-" + task["material_hash"] + ".json").read_bytes()
                    if digest(content) != task["material_hash"]:
                        raise ValueError("changed materials")
                    materials = json.loads(content)
                    if {m["id"] for m in materials} != set(task["material_ids"]):
                        raise ValueError("missing material")
                    self.materials.update({m["id"]: m for m in materials})
                except (KeyError, ValueError, OSError):
                    self.store.update("tasks", task["id"], status="interrupted", error="任务材料副本缺失或变化，请重新启动工程并附加材料")

    def snapshot(self):
        return self.store.snapshot() | {"demo": self.root is None, "confirmations": CONFIRMATIONS, "app_version": VERSION}

    @locked
    def folder(self, name, parent=None, record_id=None, collapsed=None):
        if not name.strip():
            raise ChatterError("请输入分类名称")
        cursor = parent
        seen = {record_id} if record_id else set()
        while cursor:
            if cursor in seen:
                raise ChatterError("分类不能放入自身或子分类")
            seen.add(cursor)
            cursor = self.store.get("folders", cursor).get("parent")
        values = dict(name=name.strip(), parent=parent)
        if collapsed is not None:
            values["collapsed"] = bool(collapsed)
        if record_id:
            return self.store.update("folders", record_id, **values)
        values.setdefault("collapsed", False)
        return self.store.add("folders", **values)

    def session(self, title="新会话", folder=None, record_id=None):
        if folder:
            self.store.get("folders", folder)
        if record_id:
            return self.store.update("sessions", record_id, title=title.strip() or "新会话", folder=folder)
        return self.store.add("sessions", title=title.strip() or "新会话", folder=folder,
                              character_id=None, version=None, model=None, model_preferences={})

    @locked
    def models(self, session_id, agent, model=None, effort=None, task_id=None):
        from .providers import AGENTS
        if agent not in AGENTS or any(v is not None and (not isinstance(v, str) or not v) for v in (model, effort)):
            raise ChatterError("模型配置无效")
        if task_id:
            task = self.store.get("tasks", task_id)
            if task["session_id"] != session_id or task["status"] != "needs_input" or task.get("execution"):
                raise ChatterError("工程任务开始后不能修改模型配置")
            return self.store.update("tasks", task_id, model_override={"model": model, "effort": effort})
        session = self.store.get("sessions", session_id)
        if any(t["session_id"] == session_id and t["status"] == "running" for t in self.store.rows("tasks")):
            raise ChatterError("请先停止当前会话的生成")
        preferences = session.get("model_preferences", {}) | {agent: {"model": model, "effort": effort}}
        return self.store.update("sessions", session_id, model_preferences=preferences)

    @locked
    def select_agent(self, agent):
        from .providers import AGENTS
        if agent not in AGENTS:
            raise ChatterError("未知 Agent")
        if any(t["status"] == "running" or (t["kind"] != "chat" and t["status"] == "needs_input") for t in self.store.rows("tasks")):
            raise ChatterError("请先完成或取消正在进行的生成和工程任务")
        self.store.put_setting("agent", agent)

    def authorize_provider(self, session_id, agent):
        from .providers import AGENTS
        if agent not in AGENTS:
            raise ChatterError("未知 Agent")
        session = self.store.get("sessions", session_id)
        self.store.update("sessions", session_id, authorized_agents=list(dict.fromkeys([*session.get("authorized_agents", ["codex"]), agent])))

    def settings(self, **values):
        if set(values) - {"theme", "characters_root", "model", "codex_cli", "deepseek_cli", "deepseek_auth"}:
            raise ChatterError("未知设置")
        if "deepseek_auth" in values and values["deepseek_auth"] not in ("account", "api_key"):
            raise ChatterError("未知认证方式")
        if "theme" in values and values["theme"] not in ("light", "dark"):
            raise ChatterError("主题必须为浅色或深色")
        if "characters_root" in values:
            if not self.root:
                raise ChatterError("演示模式不访问本机目录")
            path = plain_path(Path(values["characters_root"]))
            if path == self.root or path.is_relative_to(self.root / "staging"):
                raise ChatterError("角色目录不能是 data 根目录或 staging")
            path.mkdir(parents=True, exist_ok=True)
            values["characters_root"] = str(path)
        for key, value in values.items():
            self.store.put_setting(key, value)
        return self.snapshot()

    def _files(self, kind, record_id):
        record = self.store.get(kind, record_id)
        if not self.root:
            return deepcopy(self.memory_files[record_id])
        return tree(Path(record["path"]))

    def character_files(self, character_id, version=None):
        character = self.store.get("characters", character_id)
        version = version or character["version"]
        row = next((v for v in self.store.rows("versions") if v["character_id"] == character_id and v["number"] == version), None)
        if not row:
            raise ChatterError("角色版本不存在")
        files = self._files("versions", row["id"])
        if fingerprint(files) != row["hash"]:
            raise ChatterError("已保存的角色版本被外部修改，请重新导入，不会覆盖该版本")
        return files

    def _version(self, character_id, number, files):
        version_id = uid()
        path = Path(self.store.setting("characters_root")) / character_id / f"v{number}-{version_id[:8]}"
        if self.root:
            write_tree(path, files)
        else:
            self.memory_files[version_id] = deepcopy(files)
        return self.store.add("versions", id=version_id, character_id=character_id, number=number,
                              path=str(path) if self.root else "", hash=fingerprint(files))

    def import_character(self, source, category="developing", confirmed_character=False):
        if not self.root:
            raise ChatterError("演示模式不能导入本机文件")
        if not confirmed_character:
            raise ChatterError("请确认导入内容属于 character skill")
        source = plain_path(Path(source))
        if source.is_file():
            if source.name != "SKILL.md":
                raise ChatterError("请选择 SKILL.md 或其角色目录")
            source = source.parent
        return self.register(tree(source), category, str(source))

    @locked
    def register(self, files, category="developing", source=""):
        if category not in ("developing", "runtime"):
            raise ChatterError("未知角色分类")
        info = skill_info(files)
        with self.store.transaction():
            character = self.store.add("characters", **info, category=category, version=1, source=source)
            self._version(character["id"], 1, files)
        return character

    def refresh_characters(self):
        if not self.root:
            raise ChatterError("演示模式不扫描本机目录")
        root = plain_path(Path(self.store.setting("characters_root")))
        found = []
        # Only immediate manually placed packages; app-owned version trees are not reimported.
        registered = {c["id"] for c in self.store.rows("characters")}
        for entry in root.iterdir():
            if entry.name not in registered and entry.is_dir() and (entry / "SKILL.md").is_file():
                plain_path(entry)
                info = skill_info(tree(entry))
                found.append(info | {"path": str(entry)})
        return found

    def classify(self, character_id, category):
        if category not in ("developing", "runtime"):
            raise ChatterError("未知角色分类")
        return self.store.update("characters", character_id, category=category)

    @locked
    def load_character(self, session_id, character_id, version=None, choice=None):
        session = self.store.get("sessions", session_id)
        character = self.store.get("characters", character_id)
        version = version or character["version"]
        self.character_files(character_id, version)
        switching = session["character_id"] and (session["character_id"] != character_id or session["version"] != version)
        if switching and choice not in ("new", "continue"):
            return {"warning": "一个会话建议只使用一个角色，建议在新会话中试用。", "choices": ["new", "continue", "cancel"]}
        if switching and choice == "new":
            session = self.session(character["name"], session["folder"])
        self.store.update("sessions", session["id"], character_id=character_id, version=version)
        self.store.add("messages", session_id=session["id"], role="event", text=f"已加载 {character['name']} · v{version}",
                       task_id=None, metadata={"character_id": character_id, "version": version, "status": "confirmed"})
        return {"session_id": session["id"]}

    def prepare_engineering(self, session_id, role):
        self.store.get("sessions", session_id)
        if role not in ("generator", "maintainer"):
            raise ChatterError("未知工程角色")
        token = uid()
        self.confirmations[token] = (session_id, role)
        return {"token": token, "role": role, "text": CONFIRMATIONS[role]}

    @locked
    def start_engineering(self, session_id, role, token):
        if self.confirmations.pop(token, None) != (session_id, role):
            raise ChatterError("需要通过应用确认后调用该工程 skill")
        if any(t["session_id"] == session_id and (t["status"] == "running" or (t["status"] == "needs_input" and t["kind"] != "chat")) for t in self.store.rows("tasks")):
            raise ChatterError("请先完成或取消当前任务")
        session = self.store.get("sessions", session_id)
        if role == "maintainer" and not session["character_id"]:
            raise ChatterError("请先加载需要维护的角色")
        records = [r["id"] for r in self.store.rows("records") if r.get("session_id") == session_id
                   and r.get("character_id") == session["character_id"] and r.get("version") == session["version"]]
        return self.store.add("tasks", session_id=session_id, kind=role, status="needs_input",
                              character_id=session["character_id"], version=session["version"], record_ids=records, error=None)

    @locked
    def doctor(self, session_id, message_id=None, feedback="", provisional_text=None):
        if any(t["session_id"] == session_id and (t["status"] == "running" or (t["status"] == "needs_input" and t["kind"] != "chat")) for t in self.store.rows("tasks")):
            raise ChatterError("请先完成或取消当前任务")
        messages = self.store.rows("messages")
        if provisional_text is not None:
            if not provisional_text.strip():
                raise ChatterError("临时诊断需要明确提供待诊断文本")
            self.store.get("sessions", session_id)
            return self.store.add("tasks", session_id=session_id, kind="doctor", status="needs_input", character_id=None,
                                  version=None, target_message_id=None, feedback=feedback, provisional=True,
                                  provisional_text=provisional_text, error=None)
        candidates = [m for m in messages if m["session_id"] == session_id and m["role"] == "assistant" and m["metadata"].get("character_id") and not m.get("task_id")]
        target = next((m for m in candidates if m["id"] == message_id), None) if message_id else (candidates[-1] if candidates else None)
        if not target:
            raise ChatterError("请先加载角色并生成回复，再选择需要诊断的角色输出")
        return self.store.add("tasks", session_id=session_id, kind="doctor", status="needs_input",
                              character_id=target["metadata"]["character_id"], version=target["metadata"]["version"],
                              target_message_id=target["id"], feedback=feedback, error=None)

    def attach(self, path, as_skill=False):
        if not self.root:
            raise ChatterError("演示模式不读取本机材料")
        source = plain_path(Path(path))
        if as_skill:
            files = tree(source if source.is_dir() else source.parent)
            info = skill_info(files)
            value = {"name": str(source), "text": texts(files), "source": str(source), "as_skill": True, "skill_name": info["name"]}
        else:
            if not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
                raise ChatterError("请选择不超过 16 MB 的文本、Markdown 或 DOCX 文件")
            if source.suffix.lower() == ".docx":
                import zipfile
                import zlib
                from xml.etree import ElementTree
                from xml.parsers import expat
                limit = 16 * 1024 * 1024
                try:
                    with zipfile.ZipFile(source) as archive:
                        member = archive.getinfo("word/document.xml")
                        if member.file_size > limit:
                            raise ChatterError("DOCX 展开正文超过 16 MB，请拆分文件后重新导入")
                        with archive.open(member) as stream:
                            xml = stream.read(limit + 1)
                        if len(xml) > limit:
                            raise ChatterError("DOCX 展开正文超过 16 MB，请拆分文件后重新导入")
                    # A ZIP byte budget alone does not bound internal entities.
                    # Expat recognizes declarations across supported encodings;
                    # reject at DTD start, before entity expansion or tree allocation.
                    def reject_doctype(*args):
                        raise ChatterError("DOCX 正文不支持 DTD 或自定义实体；未登记材料")
                    parser = expat.ParserCreate()
                    parser.StartDoctypeDeclHandler = reject_doctype
                    parser.Parse(xml, True)
                    value_text = "\n".join(ElementTree.fromstring(xml).itertext())
                except ChatterError:
                    raise
                except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, OSError, ValueError,
                        RuntimeError, NotImplementedError, EOFError, zlib.error, expat.ExpatError, ElementTree.ParseError) as error:
                    raise ChatterError("无法读取 DOCX 正文，文件损坏或格式无效；未登记材料") from error
            elif source.suffix.lower() in (".txt", ".md", ".json", ".yaml", ".yml"):
                value_text = source.read_text(encoding="utf-8-sig")
            else:
                raise ChatterError("首版材料支持 TXT、Markdown、JSON、YAML 和 DOCX")
            value = {"name": source.name, "text": value_text, "source": str(source), "as_skill": False}
        material_id = uid()
        self.materials[material_id] = value
        return {"id": material_id, "name": source.name, "as_skill": as_skill}

    @locked
    def prepare_request(self, session_id, text, task_id=None, material_ids=()):
        session = self.store.get("sessions", session_id)
        if not text.strip():
            raise ChatterError("请输入消息")
        provisional = re.match(r"(?is)^[@$](?:style-)?doctor\s+--provisional\s+(.+)", text.strip())
        if provisional and not task_id:
            task_id = self.doctor(session_id, provisional_text=provisional[1])["id"]
        invocation_text = "" if provisional else text
        # Typed invocation and buttons share the same native review seam.
        for role in ("generator", "maintainer"):
            if re.search(r"(?i)(?:^|\s)[@$](?:character-)?" + role + r"\b", invocation_text):
                task = self.store.get("tasks", task_id) if task_id else None
                if not task or task["kind"] != role:
                    return {"confirmation_required": self.prepare_engineering(session_id, role)}
        if not task_id:
            pending = next((t for t in reversed(self.store.rows("tasks")) if t["session_id"] == session_id and t["status"] == "needs_input" and t["kind"] != "chat"), None)
            task_id = pending["id"] if pending else None
        task = self.store.get("tasks", task_id) if task_id else None
        if task and task["session_id"] != session_id:
            raise ChatterError("任务与会话不匹配")
        if task and task["status"] != "needs_input":
            raise ChatterError("任务已结束或正在运行，请重新确认工程调用")
        if any(t["session_id"] == session_id and t["status"] == "running" for t in self.store.rows("tasks")):
            raise ChatterError("当前会话仍在生成，可先停止")
        kind = task["kind"] if task else "chat"
        original_task = bool(task)
        if not task:
            task = self.store.add("tasks", session_id=session_id, kind="chat", status="needs_input",
                                  character_id=session["character_id"], version=session["version"], error=None)
        retained = task.get("material_ids", []) if kind != "chat" else []
        chosen = [deepcopy(self.materials[m]) | {"id": m} for m in dict.fromkeys([*retained, *material_ids]) if m in self.materials]
        # Explicit quoted absolute skill references are never silently registered.
        for path in re.findall(r'@"([^"\n]+)"', invocation_text):
            attached = self.attach(path, as_skill=True)
            chosen.append(deepcopy(self.materials[attached["id"]]) | {"id": attached["id"]})
        for material in chosen:
            skill_name = material.get("skill_name", "").removeprefix("character-")
            if not provisional and skill_name in CONFIRMATIONS and kind != skill_name:
                return {"confirmation_required": self.prepare_engineering(session_id, skill_name)}
        cid, version = task.get("character_id"), task.get("version")
        files = self.character_files(cid, version) if cid else {}
        messages = self.store.rows("messages")
        history = [m for m in messages if m["session_id"] == session_id and ((m.get("task_id") == task_id) if original_task else not m.get("task_id")) and m["role"] in ("user", "assistant")]
        records = [r for r in self.store.rows("records") if r["id"] in task.get("record_ids", [])]
        payload = {"role": kind, "user": text, "history": history, "character": texts(files),
                   "character_context": {"character_id": cid, "version": version, "status": "confirmed" if cid else "missing", "resource_hash": fingerprint(files)},
                   "materials": [{k: v for k, v in m.items() if k != "source"} for m in chosen], "records": records}
        if kind == "doctor":
            if task.get("provisional"):
                payload["target"] = {"role": "assistant", "text": task["provisional_text"], "metadata": {"status": "provisional"}}
                payload["character_context"]["status"] = "provisional"
            else:
                payload["target"] = self.store.get("messages", task["target_message_id"])
            payload["feedback"] = task.get("feedback", "")
            local_history = [m for m in messages if m["session_id"] == session_id and not m.get("task_id")]
            payload["history"] = [] if task.get("provisional") else local_history[:local_history.index(payload["target"]) + 1][-12:]
        material_hash = None
        if self.root:
            directory = inside(self.root / "staging", task["id"])
            directory.mkdir(parents=True, exist_ok=True)
            for material in chosen:
                if not material["as_skill"]:
                    atomic(inside(directory / "materials", material["id"] + ".txt"), str(material["text"]).encode("utf-8"))
            content = json.dumps(chosen, ensure_ascii=False, sort_keys=True).encode("utf-8")
            material_hash = digest(content)
            atomic(inside(directory, "materials-" + material_hash + ".json"), content)
        with self.store.transaction():
            self.store.update("tasks", task["id"], status="running", error=None, material_ids=[m["id"] for m in chosen], material_hash=material_hash)
            self.store.add("messages", session_id=session_id, role="user", text=text,
                           task_id=task["id"] if kind != "chat" else None, metadata={})
            if session["title"] == "新会话":
                self.store.update("sessions", session_id, title=text[:24])
        return {"task_id": task["id"], "session_id": session_id, "payload": payload,
                "model": session.get("model") or self.store.setting("model"), "materials": chosen}

    def fail(self, task_id, message, cancelled=False):
        return self.store.update("tasks", task_id, status="cancelled" if cancelled else "failed", error=message)

    @locked
    def complete(self, request, result):
        task = self.store.get("tasks", request["task_id"])
        if task["status"] != "running":
            return None
        if not isinstance(result, dict) or not isinstance(result.get("reply"), str) or result.get("status") not in ("needs_input", "completed"):
            raise ChatterError("模型返回格式无效，未提交结果")
        proposed = result.get("files", [])
        if not isinstance(proposed, list) or any(not isinstance(f, dict) or set(f) != {"path", "content"} or not isinstance(f["content"], str) for f in proposed):
            raise ChatterError("模型文件提案格式无效")
        if proposed and task["kind"] == "doctor":
            raise ChatterError("Doctor 只能诊断，不能提出文件写入")
        files = {relative(f["path"]): f["content"].encode("utf-8") for f in proposed}
        if len(files) != len(proposed):
            raise ChatterError("提案包含重复文件")
        if proposed and task["kind"] == "chat":
            allowed = {m["name"] for m in request["materials"] if not m["as_skill"]}
            # Language is not an authorization boundary. Only explicitly attached
            # documents may become suggestions; saving still requires review.
            if not set(files).issubset(allowed):
                raise ChatterError("普通对话只能修改明确提供的文稿副本")
        base_files = self.character_files(task["character_id"], task["version"]) if task.get("character_id") else {}
        if task["kind"] == "chat":
            base_files = {m["name"]: str(m["text"]).encode("utf-8") for m in request["materials"] if not m["as_skill"]}
        if files and task["kind"] == "maintainer":
            skill_info(base_files | files)
        if files and task["kind"] == "generator":
            skill_info(files)
        with self.store.transaction():
            if "execution" in request:
                task = self.store.update("tasks", task["id"], execution=deepcopy(request["execution"]))
            self.store.add("messages", session_id=task["session_id"], role="assistant", text=result["reply"],
                           task_id=task["id"] if task["kind"] != "chat" else None,
                           metadata=(request["payload"]["character_context"] if task["kind"] == "chat" else {"kind": task["kind"]}) | {"execution": request.get("execution", {})})
            if files:
                self.stage(task, files, base_files)
            for kind in ("diagnosis", "handoff"):
                body = result.get(kind, "")
                if body and task["kind"] == "doctor":
                    self.record(task, kind, body)
            self.store.update("tasks", task["id"], status=result["status"], error=None)
        return self.snapshot()

    def record(self, task, kind, body):
        record_id = uid()
        metadata = {"character_id": task.get("character_id"), "version": task.get("version"), "target_message_id": task.get("target_message_id"), "execution": task.get("execution", {})}
        if task.get("provisional"):
            metadata["status"] = "provisional"
            body = "> Provisional：角色上下文未经确认；本记录不能证明角色版本的运行表现。\n\n" + body
        header = f"---\nid: {record_id}\nkind: {kind}\ntask_id: {task['id']}\ncharacter_context: {json.dumps(metadata, ensure_ascii=False)}\n---\n\n"
        path = self.root / "records" / kind / (record_id + ".md") if self.root else None
        if path:
            atomic(path, (header + body).encode("utf-8"))
        return self.store.add("records", id=record_id, task_id=task["id"], session_id=task["session_id"], kind=kind, body=body,
                              path=str(path) if path else "", **metadata)

    def stage(self, task, changes, base_files):
        proposal_id = uid()
        path = self.root / "staging" / task["id"] / proposal_id if self.root else None
        files = (base_files | changes) if task["kind"] == "maintainer" else changes
        if path:
            write_tree(path, files)
        else:
            self.memory_files[proposal_id] = deepcopy(files)
        return self.store.add("proposals", id=proposal_id, task_id=task["id"], session_id=task["session_id"], kind=task["kind"],
                              character_id=task.get("character_id"), base_version=task.get("version"),
                              base_hash=fingerprint(base_files), hash=fingerprint(files), path=str(path) if path else "",
                              changes={k: {"before": base_files.get(k, b"").decode("utf-8", errors="replace"), "after": v.decode("utf-8")} for k, v in changes.items()}, status="pending")

    @locked
    def accept(self, proposal_id):
        with self.store.transaction():
            proposal = self.store.get("proposals", proposal_id)
            if proposal["status"] != "pending":
                raise ChatterError("该提案已经处理")
            files = self._files("proposals", proposal_id)
            if fingerprint(files) != proposal["hash"]:
                raise ChatterError("待审阅副本发生变化，请重新生成提案")
            if proposal["kind"] == "maintainer":
                character = self.store.get("characters", proposal["character_id"])
                if character["version"] != proposal["base_version"] or fingerprint(self.character_files(character["id"])) != proposal["base_hash"]:
                    raise ChatterError("角色版本发生变化，提案已保留，请根据当前版本重新维护")
                number = character["version"] + 1
                self._version(character["id"], number, files)
                self.store.update("characters", character["id"], version=number, **skill_info(files))
            elif proposal["kind"] == "generator":
                character = self.register(files)
            else:
                if not self.root:
                    self.memory_files[proposal_id + "-accepted"] = files
                else:
                    write_tree(self.root / "documents" / proposal_id, files)
                character = None
            self.store.update("proposals", proposal_id, status="accepted", accepted_character_id=character["id"] if character else None)
        return self.snapshot()

    def cancel_task(self, task_id):
        return self.fail(task_id, "用户已取消，原始文件和已保存记录保持不变", True)

    def seed_demo(self):
        """Only synthetic in-memory examples, never shipped as user characters."""
        if self.root:
            raise ChatterError("示例仅限内存演示模式")
        folder = self.folder("写作练习")
        nested = self.folder("随笔", folder["id"])
        session = self.session("关于一段文字的讨论", nested["id"])
        self.session("改写练习", nested["id"])
        experiment = self.folder("角色实验")
        self.folder("节奏测试", experiment["id"])
        files = {"SKILL.md": b"---\nname: sample-character\ndescription: Synthetic demo character only.\n---\n\nWrite restrained original prose.\n"}
        character = self.register(files, "developing")
        self.store.update("characters", character["id"], name="样例角色 A")
        second = self.register(files, "runtime")
        self.store.update("characters", second["id"], name="样例角色 B")
        self.store.update("sessions", session["id"], character_id=character["id"], version=1)
        self.store.add("messages", session_id=session["id"], role="user", text="这段话的情绪有些直白，帮我改得克制一点。", task_id=None, metadata={})
        self.store.add("messages", session_id=session["id"], role="assistant", text="那段日子里，我常常在夜里想起那次分别。它并没有想象中那样戏剧化，却在不知不觉中改变了我对许多事情的看法。\n\n回过头看，那些看似平常的细节，其实都在悄悄塑造着我。虽然仍会有些失落，但我也逐渐学会接受，并在这种接受中找到新的平衡。\n\n这是内存演示中的示例文字，不代表真实模型输出。", task_id=None, metadata={"character_id": character["id"], "version": 1, "status": "confirmed"})
        return session["id"]
