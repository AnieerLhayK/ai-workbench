"""Bounded evidence collection, branch-aware imports and read-only project intake."""
from datetime import datetime, timezone, timedelta
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import zipfile
from uuid import uuid4
from threading import Event
from collections import deque
from xml.etree import ElementTree

from ..storage import atomic_json
from ..personal_archive import query as query_archive
from .codex import AppServer
from .library import DiaryError, digest, load_json, now, is_link

EXCLUDED = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", "archives", "archive", "private-corpus"}
TEXT_TYPES = {".md", ".txt", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml", ".csv", ".tex"}


def timestamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return value if isinstance(value, str) else None


def in_period(value, start, end):
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        lower, upper = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=lower.tzinfo)
        return lower <= parsed < upper
    except (TypeError, ValueError):
        return False


class Sources:
    def __init__(self, settings, library, config=None):
        self.settings, self.library = settings, library
        self.config = config or {}
        self.memory_imports = {}

    def register(self, values):
        """Register a directory once; its initial contents are background only."""
        if self.config.get("demo"):
            raise DiaryError("演示模式不读取真实资料目录")
        previous = {item["id"]: item for item in self.settings.data["sources"]}
        registered = []
        for item in values:
            item = dict(item)
            old = previous.get(item["id"], {})
            if item.get("type") == "directory":
                if old.get("path") == item["path"] and old.get("type") == "directory" and "baseline" in old:
                    item.update({key: old[key] for key in ("baseline", "covered", "registered_at", "baseline_warnings") if key in old})
                else:
                    docs, warnings = self._directory(Path(item["path"]), Event())
                    item.update(baseline={doc["relative"]: doc["fingerprint"] for doc in docs},
                                covered={}, registered_at=now(), baseline_warnings=warnings)
            registered.append(item)
        self.settings.update(sources=registered)

    def _directory(self, root, cancelled):
        """Bounded local text/PPTX Adapter. mtime never means activity time."""
        if not root.is_absolute() or not root.is_dir() or any(is_link(p) for p in [root, *root.parents]):
            raise DiaryError("普通目录来源必须是存在的非链接绝对目录")
        documents, warnings, pending = [], [], deque([root])
        visited, consumed = 0, 0
        while pending:
            directory = pending.popleft()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if cancelled.is_set():
                        raise DiaryError("任务已取消")
                    visited += 1
                    if visited > 2000 or len(documents) >= 200:
                        return documents, [*warnings, "普通目录达到 2000 项或 200 文件预算，部分材料未读取"]
                    path = Path(entry.path)
                    if entry.name.lower() in EXCLUDED or is_link(path):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=False) or path.suffix.lower() not in TEXT_TYPES | {".pptx"}:
                        continue
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                        if size > 8_000_000 or consumed + size > 16_000_000:
                            warnings.append(f"普通目录读取预算不足，未读取：{path.name}")
                            continue
                        with path.open("rb") as stream:
                            raw = stream.read(8_000_001)
                        if len(raw) > 8_000_000:
                            raise DiaryError("文件超过 8 MB")
                        consumed += len(raw)
                        body = self._slides(raw) if path.suffix.lower() == ".pptx" else raw.decode("utf-8-sig")
                        relative = path.relative_to(root).as_posix()
                        documents.append({"id": "directory:" + str(path), "title": relative, "body": body[:16000],
                                          "path": str(path), "relative": relative, "complete": len(body) <= 16000,
                                          "fingerprint": hashlib.sha256(raw).hexdigest(), "at": None, "origin": "directory"})
                        if len(body) > 16000:
                            warnings.append(f"普通目录正文已截短，未推进该文件覆盖：{relative}")
                    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as error:
                        warnings.append(f"普通目录文件未读取：{path.name}（{error}）")
        return documents, warnings

    @staticmethod
    def _slides(raw):
        import io
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = sorted((item for item in archive.infolist() if
                              re.fullmatch(r"ppt/(?:slides/slide|notesSlides/notesSlide)\d+\.xml", item.filename)),
                             key=lambda item: (item.filename.split('/')[1], int(re.search(r"(\d+)\.xml", item.filename)[1])))
            if not members or len(members) > 200 or sum(item.file_size for item in members) > 8_000_000:
                raise DiaryError("PPTX 内容为空或超过提取预算")
            parts = []
            for item in members:
                with archive.open(item) as stream:
                    xml = stream.read(1_000_001)
                if len(xml) > 1_000_000:
                    raise DiaryError("PPTX 页面超过提取预算")
                if b"<!DOCTYPE" in xml.replace(b"\x00", b"").upper() or b"<!ENTITY" in xml.replace(b"\x00", b"").upper():
                    raise DiaryError("PPTX 包含不支持的 DTD 或实体")
                tree = ElementTree.fromstring(xml)
                texts = [node.text for node in tree.iter() if node.tag.endswith("}t") and node.text]
                parts.append(item.filename + "\n" + "\n".join(texts))
            return "\n\n".join(parts)

    def acknowledge(self, bundle, request):
        """Only successfully saved normal work reports consume adopted versions."""
        if request["kind"] != "work" or request.get("comparison"):
            return
        adopted = bundle.get("directory_versions", {})
        if not adopted:
            return
        from copy import deepcopy
        sources = deepcopy(self.settings.data["sources"])
        for source in sources:
            value = adopted.get(source["id"])
            if value and value["path"] == source["path"] and value["registered_at"] == source.get("registered_at"):
                source.setdefault("covered", {}).update(value["files"])
        self.settings.update(sources=sources)

    def import_file(self, path):
        if self.config.get("demo"):
            raise DiaryError("演示模式不读取真实导入文件")
        path = Path(path)
        if path.stat().st_size > 150_000_000:
            raise DiaryError("导入文件超过 150 MB，请拆分后导入")
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                candidates = [i for i in archive.infolist() if Path(i.filename).name == "conversations.json"]
                if len(candidates) != 1 or candidates[0].file_size > 150_000_000:
                    raise DiaryError("导出包须包含一个不超过 150 MB 的 conversations.json")
                text = archive.read(candidates[0]).decode("utf-8-sig")
        else:
            text = path.read_text(encoding="utf-8-sig")
        key = digest(text)
        if any(i["hash"] == key for i in self.settings.data["imports"]):
            return 0
        documents = []
        if path.suffix.lower() in (".json", ".zip"):
            value = json.loads(text)
            conversations = value if isinstance(value, list) else value.get("conversations", [value])
            for conversation in conversations:
                mapping = conversation.get("mapping", {})
                if mapping:
                    for node_id, node in mapping.items():
                        message = node.get("message") or {}
                        role = message.get("author", {}).get("role")
                        parts = message.get("content", {}).get("parts", [])
                        body = "\n".join(p for p in parts if isinstance(p, str))
                        if body and role in ("user", "assistant"):
                            documents.append({"id": f"chatgpt:{conversation.get('id', key)}:{node_id}",
                                "title": conversation.get("title", "ChatGPT 对话"), "body": body,
                                "at": timestamp(message.get("create_time")), "role": role,
                                "parent": node.get("parent"), "children": node.get("children", []), "origin": "chatgpt"})
                elif isinstance(conversation.get("messages"), list):
                    for n, message in enumerate(conversation["messages"]):
                        documents.append({"id": f"import:{key}:{n}", "title": conversation.get("title", path.stem),
                            "body": str(message.get("content", "")), "role": message.get("role", "unknown"),
                            "at": timestamp(message.get("create_time") or message.get("timestamp")), "origin": "chatgpt"})
                elif isinstance(conversation.get("body"), str):
                    documents.append({"id": f"import:{key}", "title": conversation.get("title", path.stem),
                        "body": conversation["body"], "at": timestamp(conversation.get("date")), "origin": "import"})
        else:
            documents = [{"id": f"import:{key}", "title": path.stem, "body": text, "at": None, "origin": "import"}]
        if not documents:
            raise DiaryError("未找到可导入的对话文本；支持 ChatGPT 导出 mapping、messages 或 body 格式")
        item = {"id": uuid4().hex, "hash": key, "name": path.name, "imported_at": now(), "count": len(documents)}
        if self.library.root:
            atomic_json(self.library.root / "imports" / (item["id"] + ".json"), {"documents": documents})
        else:
            self.memory_imports[item["id"]] = documents
        self.settings.update(imports=[*self.settings.data["imports"], item])
        return len(documents)

    def _git(self, root, start, end):
        def run(*args):
            result = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(root), *args], capture_output=True,
                                    encoding="utf-8", errors="replace", timeout=20,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise DiaryError(f"项目 Git 读取失败：{root.name}")
            return result.stdout
        log = run("log", "--all", "--since=" + start, "--until=" + end,
                  "--format=%H %aI %s", "--max-count=150")
        names = run("log", "--all", "--since=" + start, "--until=" + end,
                    "--format=", "--name-only", "--max-count=150").splitlines()
        status = run("status", "--short", "--untracked-files=no")
        docs = [{"id": "git:" + str(root), "title": root.name + " · Git 活动", "body": log + "\n当前未提交状态（不代表过去已完成）：\n" + status,
                 "at": end, "origin": "git", "path": str(root)}]
        for name in list(dict.fromkeys(names))[:30]:
            relative = Path(name.strip())
            if relative.drive or relative.root or relative.is_absolute() or any(p.lower() in EXCLUDED or p == ".." for p in relative.parts):
                continue
            path = root / relative
            if any(is_link(p) for p in [path, *list(path.parents)[:len(relative.parts)]]):
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            if path.is_file() and path.suffix.lower() in TEXT_TYPES and path.stat().st_size < 100_000:
                docs.append({"id": "file:" + str(path), "title": str(relative),
                    "body": path.read_text(encoding="utf-8", errors="replace")[:12000], "at": None,
                    "origin": "file", "path": str(path), "timing": "当前文件，只作为活动背景；不以修改时间证明完成"})
        return docs

    def _sessions(self, start, end, cancelled):
        executable = self.config.get("codex_cli")
        if not executable:
            raise DiaryError("未配置 Codex CLI")
        server = AppServer(executable, self.config.get("staging_root") or str(self.library.root), cancelled)
        result, characters = [], 0
        self.session_warnings = []
        try:
            for page in self._thread_pages(server, start):
                for thread in page:
                    if thread["id"] in self.settings.data["own_threads"]:
                        continue
                    at = timestamp(thread.get("updatedAt"))
                    if not at or datetime.fromisoformat(at) < datetime.fromisoformat(start):
                        continue
                    turns, turn_cursor = [], None
                    for _ in range(10):
                        history = server.request("thread/turns/list", {"threadId": thread["id"],
                            "limit": 50, "cursor": turn_cursor, "sortDirection": "desc", "itemsView": "full"})
                        turns.extend(history["data"])
                        turn_cursor = history.get("nextCursor")
                        if not turn_cursor:
                            break
                    for turn in turns:
                        turn_at = timestamp(turn.get("startedAt"))
                        if turn_at and not in_period(turn_at, start, end):
                            continue
                        if not turn_at and not in_period(at, start, end):
                            continue
                        texts = []
                        for item in turn.get("items", []):
                            if item.get("type") == "agentMessage":
                                texts.append("助手记录：" + item.get("text", ""))
                            elif item.get("type") == "userMessage":
                                texts.extend("用户输入：" + i.get("text", "") for i in item.get("content", []) if i.get("type") == "text")
                        if texts:
                            characters += sum(len(text) for text in texts)
                            result.append({"id": "codex:" + thread["id"] + ":" + turn["id"],
                                "title": thread.get("name") or thread.get("preview", "Codex 会话"),
                                "body": "\n".join(texts), "at": turn_at,
                                "timing": "逐轮时间" if turn_at else "仅会话更新时间落在范围内，轮次日期未知，勿认定为本期完成",
                                "origin": "codex"})
                            if characters >= 140000:
                                self.session_warnings.append("会话资料达到 14 万字符读取上限；请缩小时期以获得更完整覆盖")
                                return result
        finally:
            server.close()
        return result

    def _thread_pages(self, server, start):
        for archived in (False, True):
            cursor = None
            for _ in range(20):
                page = server.request("thread/list", {"limit": 50, "cursor": cursor,
                    "sortKey": "updated_at", "sortDirection": "desc", "useStateDbOnly": True,
                    "sourceKinds": ["cli", "vscode", "appServer", "exec"], "archived": archived})
                yield page["data"]
                cursor = page.get("nextCursor")
                if not cursor or (page["data"] and page["data"][-1].get("updatedAt", 0) < datetime.fromisoformat(start).timestamp()):
                    break
            else:
                self.session_warnings.append("会话列表达到分页上限，未读取更早页面")

    def _history(self, request, cancelled, warnings):
        start = datetime.fromisoformat(request["start"]).date()
        lower = start - timedelta(days=180)
        docs, budget = [], 24000
        for kind, limit in (("diary", 20), (request["kind"], 8)):
            # Select descriptors before reading bodies: the limits bound actual reads.
            records = [record for record in self.library.metadata(kind=kind)
                       if lower.isoformat() <= record["date"] < start.isoformat()]
            if len(records) > limit:
                warnings.append("历史背景达到篇数上限，部分旧记录未纳入")
            for record in records[:limit]:
                if cancelled.is_set():
                    raise DiaryError("任务已取消")
                if not budget:
                    warnings.append("历史背景达到 24000 字符预算，部分旧记录未纳入")
                    break
                record = self.library.read(record["id"])
                text = record["body"][:min(2400, budget)]
                if not text:
                    continue
                if len(text) < len(record["body"]):
                    warnings.append("历史背景正文已截短，仅用于有依据的有限理解")
                budget -= len(text)
                docs.append({"id": "history:" + record["id"], "title": record["title"], "body": text,
                             "at": record["date"], "origin": kind, "evidence_role": "historical_background",
                             "role": "user" if kind == "diary" else "generated",
                             "timing": "报告周期之前的长期背景；历史生成报告只辅助理解，不能独立证明事实"})
        return docs

    def collect(self, request, cancelled, progress):
        if cancelled.is_set():
            raise DiaryError("任务已取消")
        documents, warnings = [], []
        directory_documents, directory_sources = [], {}
        start, end = request["start"], request["end"]
        included = request.get("include", ["diary", "development", "work"])
        for kind in included:
            for record in self.library.metadata(kind=kind):
                if cancelled.is_set():
                    raise DiaryError("任务已取消")
                period = record.get("period")
                if period:
                    if period["start"] >= end or period["end"] <= start:
                        continue
                elif not start[:10] <= record["date"] < end[:10]:
                    continue
                if record["id"] == request.get("comparison_of"):
                    continue
                record = self.library.read(record["id"])
                documents.append({"id": record["id"], "title": record["title"], "body": record["body"],
                    "at": record["date"], "origin": kind,
                    "role": "user" if kind == "diary" else "generated",
                    "evidence_role": "self_report" if kind == "diary" else "generated_context"})
        if self.config.get("demo"):
            return {"documents": documents, "warnings": ["演示模式仅使用内存示例，不读取真实资料"], "start": start, "end": end}
        history = self._history(request, cancelled, warnings) if request["kind"] in ("development", "work", "personal") else []
        if request["kind"] in ("development", "work", "personal") and not history:
            warnings.append("未找到本期之前的长期回顾背景；不能据此断言长期取向或变化")
        for item in self.settings.data["imports"]:
            docs = (load_json(self.library.root / "imports" / (item["id"] + ".json"))["documents"]
                    if self.library.root else self.memory_imports[item["id"]])
            for doc in docs:
                if in_period(doc.get("at"), start, end) or not doc.get("at"):
                    evidence = dict(doc, timing="原始消息时间" if doc.get("at") else "时间未知，仅作背景，不认定为本期活动")
                    if request["kind"] == "personal":
                        evidence["evidence_role"] = "self_report" if doc.get("role") == "user" and in_period(doc.get("at"), start, end) else "auxiliary_context"
                    documents.append(evidence)
        if request["kind"] != "personal" and self.config.get("read_codex", True):
            progress("读取 Codex 历史")
            try:
                documents += self._sessions(start, end, cancelled)
                warnings += self.session_warnings
            except (DiaryError, OSError) as error:
                warnings.append(str(error))
        if request["kind"] != "personal":
            for source in self.settings.data["sources"]:
                if not source.get("enabled"):
                    continue
                root = Path(source["path"])
                if source.get("type") == "directory":
                    if request["kind"] != "work":
                        continue
                    progress("读取普通目录工作资料")
                    try:
                        docs, limits = self._directory(root, cancelled)
                        warnings += limits + source.get("baseline_warnings", [])
                        if "baseline" not in source:
                            warnings.append(f"普通目录尚未建立基线，请在资料来源保存登记：{root.name}")
                            continue
                        directory_sources[source["id"]] = {"path": source["path"], "registered_at": source["registered_at"], "files": {}}
                        for doc in docs:
                            covered = source.get("covered", {}).get(doc["relative"], source["baseline"].get(doc["relative"]))
                            changed = covered != doc["fingerprint"]
                            doc.update(source_id=source["id"], changed=changed,
                                       timing="此次新发现或内容变化的实验室材料；可能涉及早期工作，须声明与报告日期不完全重叠，不以文件更新时间认定完成日期" if changed else
                                              "存量或已覆盖的实验室背景，不认定为本期新增工作",
                                       evidence_role="delayed_evidence" if changed else "historical_background")
                        directory_documents += sorted(docs, key=lambda doc: not doc["changed"])
                    except (OSError, DiaryError) as error:
                        if cancelled.is_set():
                            raise
                        warnings.append(f"普通目录未读取：{root.name}（{error}）")
                    continue
                if not root.is_dir() or is_link(root):
                    warnings.append(f"目录缺失或是链接：{root}")
                    continue
                roots = [root] if source.get("type") == "git" else [p for p in root.iterdir()
                    if p.is_dir() and not is_link(p) and p.name.lower() not in EXCLUDED and (p / ".git").exists()]
                for project in roots[:30]:
                    if cancelled.is_set():
                        raise DiaryError("任务已取消")
                    try:
                        documents += self._git(project, start, end)
                    except (DiaryError, OSError, subprocess.TimeoutExpired) as error:
                        warnings.append(str(error))
            warnings.append("项目资料为定向采集：每根目录最多 30 个直接 Git 子项目，每项目最多 150 条提交和 30 个当前文本文件；不是全部文件清单")
        for value in request.get("extra_paths", []):
            path = Path(value)
            if not path.is_absolute() or any(is_link(p) for p in [path, *path.parents]):
                raise DiaryError("本次资料必须是明确的绝对路径，且不能是链接")
            if path.is_dir():
                paths = [p for p in path.iterdir() if p.is_file() and not is_link(p) and p.suffix.lower() in TEXT_TYPES][:30]
            else:
                paths = [path]
            for candidate in paths:
                if candidate.stat().st_size > 1_000_000:
                    warnings.append(f"本次文件过大，未读取：{candidate.name}")
                    continue
                documents.append({"id": "extra:" + str(candidate), "title": candidate.name,
                    "body": candidate.read_text(encoding="utf-8", errors="replace"), "at": None,
                    "origin": "extra", "path": str(candidate), "timing": "本次明确授权的补充资料"})
        # Keep a dedicated laboratory slice before general session evidence.
        laboratory, lab_count = [], 0
        for doc in sorted(directory_documents, key=lambda doc: (not doc["changed"], Path(doc["relative"]).suffix.lower() != ".pptx")):
            if lab_count + len(doc["body"]) > 40000:
                warnings.append("实验室材料达到 4 万字符预算，未纳入部分不会推进覆盖")
                continue
            laboratory.append(doc)
            lab_count += len(doc["body"])
            if doc["changed"] and doc["complete"]:
                directory_sources[doc["source_id"]]["files"][doc["relative"]] = doc["fingerprint"]
        archive_documents = []
        use_archive = request["kind"] == "personal" or (request["kind"] == "report" and request.get("personal_archive", False))
        if use_archive:
            archive_root = self.config.get("personal_archive_root")
            if archive_root:
                progress("查询已确认个人档案")
                search = "\n".join([request.get("prompt", ""), json.dumps(request.get("topic", {}), ensure_ascii=False),
                    *[d["title"] + "\n" + d["body"] for d in documents if d.get("role") == "user"]])
                archive = query_archive(archive_root, search, period=(start, end))
                warnings.extend(archive["warnings"])
                for record in archive["records"]:
                    archive_documents.append({"id": "archive:" + record["id"], "title": record["title"],
                        "body": json.dumps(record, ensure_ascii=False), "at": record.get("validity", {}).get("from"),
                        "origin": "personal_archive", "role": "owner_confirmed", "evidence_role": "long_term_context",
                        "claim_kind": record["kind"], "fingerprint": record["fingerprint"], "path": record["path"],
                        "validity": record.get("validity", {}),
                        "timing": record["timing"]})
            else:
                warnings.append("尚未配置个人档案；本次没有档案背景，不能据此推断个人事实")
        unique, count = {}, 0
        if request["kind"] == "personal":
            primary = [doc for doc in documents if doc.get("evidence_role") == "self_report"]
            auxiliary = [doc for doc in documents if doc.get("evidence_role") != "self_report"]
            ordered = [*primary, *archive_documents, *history, *auxiliary]
        else:
            ordered = [*laboratory, *archive_documents, *history, *documents]
        reserved_archive = sum(len(d["body"]) for d in archive_documents)
        for doc in ordered:
            if doc["id"] in unique:
                continue
            if doc.get("origin") == "personal_archive":
                reserved_archive -= len(doc["body"])
            limit = 180000 - reserved_archive
            if count + len(doc["body"]) > limit:
                warnings.append("资料达到单次 18 万字符上限，部分材料未纳入；可缩小范围后生成")
                if request["kind"] != "personal" or count >= 180000:
                    break
                doc = dict(doc, body=doc["body"][:max(0, limit-count)], coverage_limit="正文因单次材料预算截短，不能推定未读部分")
                if not doc["body"]:
                    continue
            unique[doc["id"]] = doc
            count += len(doc["body"])
        return {"documents": list(unique.values()), "warnings": list(dict.fromkeys(warnings)), "start": start, "end": end,
                "directory_versions": directory_sources}
