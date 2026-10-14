"""DiaryLibrary Module. A committed descriptor points to immutable text revisions."""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from functools import wraps
from uuid import uuid4

from ..storage import atomic_json

KINDS = {"diary": "日记", "development": "开发", "work": "工作", "personal": "个人回顾"}


class DiaryError(ValueError):
    pass


class Conflict(DiaryError):
    """The caller's base text no longer matches the current file."""


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def is_link(path):
    path = Path(path)
    return path.is_symlink() or path.is_junction()


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


def period_label(period):
    if not period:
        return ""
    from datetime import timedelta
    end = period["end"]
    if "T" in end:
        end = (datetime.fromisoformat(end) - timedelta(microseconds=1)).date().isoformat()
    return period["start"][:10] + " — " + end[:10]


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path, default=None):
    if not path.exists():
        return deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise DiaryError(f"数据无法读取，原文件已保留：{path.name}") from error


class DiaryLibrary:
    def __init__(self, root=None):
        self.lock = threading.RLock()
        if root and is_link(root):
            raise DiaryError("数据目录不允许链接跳转")
        self.root = Path(root).resolve() if root is not None else None
        self.memory = {}
        self.records = {}
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            self.refresh()

    def _directory(self, entry_id):
        if not re.fullmatch(r"[0-9a-f]{32}", entry_id):
            raise DiaryError("无效记录标识")
        path = self.root / "entries" / entry_id
        if is_link(path) or (path.exists() and path.resolve() != path):
            raise DiaryError("记录目录不允许链接跳转")
        return path

    @synchronized
    def refresh(self):
        if not self.root:
            return
        records = {}
        base = self.root / "entries"
        if is_link(base):
            raise DiaryError("记录根目录不允许链接跳转")
        if base.exists():
            for directory in base.iterdir():
                if is_link(directory) or not directory.is_dir():
                    continue
                descriptor = directory / "record.json"
                if not descriptor.exists():
                    continue
                record = load_json(descriptor)
                try:
                    if record["id"] != directory.name or record["kind"] not in KINDS:
                        raise ValueError()
                    self._directory(record["id"])
                    date.fromisoformat(record["date"])
                    self._body_path(record)
                    if not isinstance(record["versions"], list):
                        raise ValueError()
                    if not isinstance(record.get("title"), str) or not isinstance(record.get("tags"), list) or any(not isinstance(tag, str) for tag in record["tags"]):
                        raise ValueError()
                except (KeyError, TypeError, ValueError) as error:
                    raise DiaryError(f"记录格式损坏，原文件已保留：{directory.name}") from error
                records[record["id"]] = record
        self.records = records

    def _body_path(self, record):
        name = record["file"]
        if Path(name).name != name or Path(name).suffix not in (".md", ".txt"):
            raise DiaryError("正文文件路径无效")
        path = self._directory(record["id"]) / name
        if is_link(path):
            raise DiaryError("正文不允许链接跳转")
        return path

    @synchronized
    def read(self, entry_id):
        record = deepcopy(self.records[entry_id])
        try:
            record["body"] = (self._body_path(record).read_text(encoding="utf-8-sig")
                              if self.root else self.memory[entry_id][record["file"]])
        except (OSError, UnicodeError) as error:
            raise DiaryError("正文无法读取；请恢复文件或修复编码") from error
        record["hash"] = digest(record["body"])
        return record

    @synchronized
    def query(self, kind=None, text="", month="", deleted=False, start=None, end=None):
        self.refresh()
        found = []
        for entry_id, metadata in self.records.items():
            if bool(metadata.get("deleted")) != deleted or (kind and metadata["kind"] != kind):
                continue
            if month and not metadata["date"].startswith(month):
                continue
            if start and metadata["date"] < str(start):
                continue
            if end and metadata["date"] > str(end):
                continue
            record = self.read(entry_id)
            haystack = " ".join([record["title"], record["body"], *record["tags"]]).casefold()
            if text.casefold() in haystack:
                found.append(record)
        return sorted(found, key=lambda r: (r["date"], r["updated_at"]), reverse=True)

    @synchronized
    def save(self, fields, entry_id=None, expected_hash=None):
        fields = deepcopy(fields)
        try:
            date.fromisoformat(fields["date"])
            if fields["kind"] not in KINDS or fields.get("format", ".md") not in (".md", ".txt"):
                raise ValueError()
            if not all(isinstance(fields[key], str) for key in ("title", "body")):
                raise ValueError()
            if not isinstance(fields.get("tags", []), list) or any(not isinstance(tag, str) for tag in fields.get("tags", [])):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as error:
            raise DiaryError("请检查日期、正文和格式") from error
        if entry_id:
            self.refresh()
            old = self.read(entry_id)
            if expected_hash is not None and old["hash"] != expected_hash:
                raise Conflict("外部文件已修改；你的编辑仍保留，请先处理冲突")
            record = deepcopy(self.records[entry_id])
        else:
            entry_id = uuid4().hex
            record = {"id": entry_id, "created_at": now(), "versions": [], "deleted": False}
        extension = fields.get("format", record.get("format", ".md"))
        filename = f"{fields['date']}__{uuid4().hex[:12]}{extension}"
        for key in ("date", "title", "kind", "tags", "period", "sources", "charts", "provenance"):
            if key in fields:
                record[key] = fields[key]
        record.setdefault("tags", [])
        record["title"] = record["title"].strip() or "未命名日记"
        record.update(file=filename, format=extension, updated_at=now())
        metadata = {key: deepcopy(value) for key, value in record.items() if key != "versions"}
        record["versions"].append({"file": filename, "at": record["updated_at"],
                                   "title": record["title"], "date": record["date"], "metadata": metadata})
        if self.root:
            directory = self._directory(entry_id)
            atomic_text(directory / filename, fields["body"])
            # Descriptor is the only commit point. Failed commits preserve the old pointer.
            atomic_json(directory / "record.json", record)
        else:
            self.memory.setdefault(entry_id, {})[filename] = fields["body"]
        self.records[entry_id] = record
        return self.read(entry_id)

    @synchronized
    def _flag(self, entry_id, deleted):
        record = deepcopy(self.records[entry_id])
        record.update(deleted=deleted, updated_at=now())
        if self.root:
            atomic_json(self._directory(entry_id) / "record.json", record)
        self.records[entry_id] = record

    def delete(self, entry_id):
        self._flag(entry_id, True)

    def restore(self, entry_id):
        self._flag(entry_id, False)

    @synchronized
    def purge(self, entry_id, *, confirmed=False):
        if not confirmed or not self.records[entry_id].get("deleted"):
            raise DiaryError("永久删除须确认，且记录须已在回收站中")
        if self.root:
            shutil.rmtree(self._directory(entry_id))
        self.records.pop(entry_id)
        self.memory.pop(entry_id, None)

    @synchronized
    def version(self, entry_id, number):
        record = deepcopy(self.records[entry_id])
        version = record["versions"][number]
        historical = deepcopy(version.get("metadata"))
        if historical is None:
            # Early first-version files may already be in use. Never attach
            # current-generation evidence to an older body with unknown metadata.
            historical = dict(record, file=version["file"], title=version["title"], date=version["date"],
                format=Path(version["file"]).suffix, tags=[], sources=[], charts=[], period={},
                provenance={"warnings": ["这个早期版本未保存完整元数据，未推定其来源"]})
        for key, default in (("sources", []), ("charts", []), ("provenance", {}), ("period", {})):
            historical.setdefault(key, deepcopy(default))
        historical["body"] = (self._body_path(historical).read_text(encoding="utf-8-sig")
                              if self.root else self.memory[entry_id][version["file"]])
        return historical
