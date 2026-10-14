"""Bounded evidence collection, branch-aware imports and read-only project intake."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import zipfile
from uuid import uuid4

from ..storage import atomic_json
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
            if relative.is_absolute() or any(p.lower() in EXCLUDED or p == ".." for p in relative.parts):
                continue
            path = root / relative
            if any(is_link(p) for p in [path, *list(path.parents)[:len(relative.parts)]]):
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

    def collect(self, request, cancelled, progress):
        documents, warnings = [], []
        start, end = request["start"], request["end"]
        included = request.get("include", ["diary", "development", "work"])
        for kind in included:
            for record in self.library.query(kind=kind):
                period = record.get("period")
                if period:
                    if period["start"] >= end or period["end"] <= start:
                        continue
                elif not start[:10] <= record["date"] < end[:10]:
                    continue
                documents.append({"id": record["id"], "title": record["title"], "body": record["body"],
                    "at": record["date"], "origin": kind})
        if self.config.get("demo"):
            return {"documents": documents, "warnings": ["演示模式仅使用内存示例，不读取真实资料"], "start": start, "end": end}
        for item in self.settings.data["imports"]:
            docs = (load_json(self.library.root / "imports" / (item["id"] + ".json"))["documents"]
                    if self.library.root else self.memory_imports[item["id"]])
            for doc in docs:
                if in_period(doc.get("at"), start, end) or not doc.get("at"):
                    documents.append(dict(doc, timing="原始消息时间" if doc.get("at") else "时间未知，仅作背景，不认定为本期活动"))
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
        unique, count = {}, 0
        for doc in documents:
            if doc["id"] in unique:
                continue
            if count + len(doc["body"]) > 180000:
                warnings.append("资料达到单次 18 万字符上限，部分材料未纳入；可缩小范围后生成")
                break
            unique[doc["id"]] = doc
            count += len(doc["body"])
        return {"documents": list(unique.values()), "warnings": list(dict.fromkeys(warnings)), "start": start, "end": end}
