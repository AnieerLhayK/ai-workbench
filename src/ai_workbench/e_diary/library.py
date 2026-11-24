"""DiaryLibrary: committed current diaries and versioned summary records."""
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


def normalize_body(text):
    """Match UTF-8 BOM removal and universal-newline decoding used for reads."""
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def digest(text):
    return hashlib.sha256(normalize_body(text).encode("utf-8")).hexdigest()


def matches_body_digest(path, expected):
    """Accept canonical digests and raw digests from earlier pending saves."""
    return matches_body_snapshot(path.read_bytes(), expected)


def matches_body_snapshot(raw, expected):
    return (digest(raw.decode("utf-8-sig")) == expected or
            hashlib.sha256(raw).hexdigest() == expected)


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
        self.directories = {}
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            self.refresh()

    def _directory(self, entry_id):
        if not re.fullmatch(r"[0-9a-f]{32}", entry_id):
            raise DiaryError("无效记录标识")
        path = self.root / "entries" / self.directories.get(entry_id, entry_id)
        if is_link(path) or (path.exists() and path.resolve() != path):
            raise DiaryError("记录目录不允许链接跳转")
        return path

    def _recover_save(self, directory, record):
        """Finish or roll back one interrupted diary save using its commit pointer."""
        pending = directory / ".save-pending.json"
        if not pending.exists():
            return directory
        if is_link(pending):
            raise DiaryError("保存恢复记录不允许链接跳转")
        journal = load_json(pending)
        try:
            old, new = journal["old_file"], journal["new_file"]
            if journal["id"] != record["id"] or old == new:
                raise ValueError()
            for name in (new,) if old is None else (old, new):
                if not isinstance(name, str) or Path(name).name != name or Path(name).suffix not in (".md", ".txt"):
                    raise ValueError()
                if is_link(directory / name):
                    raise ValueError()
            if record["file"] not in (old, new):
                raise ValueError()
            committed = record["file"] == new
            for name, expected in ((new, journal["new_hash"]), (old, journal["old_hash"])):
                if name is None:
                    continue
                if committed and name == new:
                    continue  # The current body may have been edited externally.
                path = directory / name
                if path.exists() and not matches_body_digest(path, expected):
                    raise ValueError()
            if not (directory / record["file"]).is_file():
                raise ValueError()
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise DiaryError("保存恢复信息不一致，原文件已保留") from error
        if committed and record["id"] in self.records:
            self.records[record["id"]] = deepcopy(record)
        discarded = old if committed else new
        if discarded is not None:
            (directory / discarded).unlink(missing_ok=True)
        if committed:
            directory = self._rename_dated_directory(directory, record["date"])
            if record["id"] in self.directories:
                self.directories[record["id"]] = directory.name
        (directory / pending.name).unlink()
        return directory

    def _recover_uncommitted_creation(self, directory):
        pending = directory / ".save-pending.json"
        if not pending.exists():
            return
        if is_link(pending):
            raise DiaryError("保存恢复记录不允许链接跳转")
        journal = load_json(pending)
        try:
            name = journal["new_file"]
            if journal["old_file"] is not None or not re.fullmatch(r"[0-9a-f]{32}", journal["id"]):
                raise ValueError()
            if not isinstance(name, str) or Path(name).name != name or Path(name).suffix not in (".md", ".txt"):
                raise ValueError()
            path = directory / name
            if is_link(path) or (path.exists() and not matches_body_digest(path, journal["new_hash"])):
                raise ValueError()
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise DiaryError("新日记恢复信息不一致，原文件已保留") from error
        if path.exists():
            record = journal.get("record")
            if not isinstance(record, dict) or record.get("id") != journal["id"] or record.get("file") != name or record.get("kind") != "diary":
                raise DiaryError("新日记恢复信息不一致，原文件已保留")
            atomic_json(directory / "record.json", record)
            pending.unlink()
            return
        pending.unlink()
        try:
            directory.rmdir()
        except OSError:
            pass

    def _rename_dated_directory(self, directory, day):
        if directory.name == day or re.fullmatch(re.escape(day) + r"-(?:[2-9]\d*|1\d+)", directory.name):
            return directory
        number = 1
        while True:
            target = directory.parent / (day if number == 1 else f"{day}-{number}")
            if not target.exists() and not is_link(target):
                directory.rename(target)
                return target
            number += 1

    @synchronized
    def refresh(self):
        if not self.root:
            return
        records = {}
        directories = {}
        base = self.root / "entries"
        if is_link(base):
            raise DiaryError("记录根目录不允许链接跳转")
        if base.exists():
            for directory in list(base.iterdir()):
                if is_link(directory) or not directory.is_dir():
                    continue
                descriptor = directory / "record.json"
                if not descriptor.exists():
                    self._recover_uncommitted_creation(directory)
                    if not descriptor.exists():
                        continue
                record = load_json(descriptor)
                try:
                    if not re.fullmatch(r"[0-9a-f]{32}", record["id"]) or record["kind"] not in KINDS or record["id"] in records:
                        raise ValueError()
                    original_date = record["date"]
                    canonical_date = date.fromisoformat(original_date).isoformat()
                    valid_names = (original_date, canonical_date)
                    dated_name = bool(re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}(?:-(?:[2-9]\d*|1\d+))?", directory.name
                    )) or any(
                        directory.name == day or re.fullmatch(
                            re.escape(day) + r"-(?:[2-9]\d*|1\d+)", directory.name
                        ) for day in valid_names
                    )
                    if directory.name != record["id"] and (record["kind"] != "diary" or not dated_name):
                        raise ValueError()
                    if directory.resolve() != directory:
                        raise ValueError()
                    directories[record["id"]] = directory.name
                    record["date"] = canonical_date
                    self._body_path(record, directory)
                    if not isinstance(record["versions"], list):
                        raise ValueError()
                    if not isinstance(record.get("title"), str) or not isinstance(record.get("tags"), list) or any(not isinstance(tag, str) for tag in record["tags"]):
                        raise ValueError()
                except (KeyError, TypeError, ValueError) as error:
                    raise DiaryError(f"记录格式损坏，原文件已保留：{directory.name}") from error
                if record["kind"] == "diary":
                    directory = self._recover_save(directory, record)
                    directories[record["id"]] = directory.name
                records[record["id"]] = record
        self.records = records
        self.directories = directories

    def _dated_directory(self, entry_id, day):
        base = self.root / "entries"
        base.mkdir(parents=True, exist_ok=True)
        current = self.directories.get(entry_id)
        if current and (current == day or re.fullmatch(re.escape(day) + r"-(?:[2-9]\d*|1\d+)", current)):
            return base / current
        number = 1
        while True:
            name = day if number == 1 else f"{day}-{number}"
            target = base / name
            if not target.exists() and not is_link(target):
                break
            number += 1
        if current:
            (base / current).rename(target)
        else:
            target.mkdir()
        self.directories[entry_id] = name
        return target

    def _body_path(self, record, directory=None):
        name = record["file"]
        if Path(name).name != name or Path(name).suffix not in (".md", ".txt"):
            raise DiaryError("正文文件路径无效")
        path = (directory or self._directory(record["id"])) / name
        if is_link(path):
            raise DiaryError("正文不允许链接跳转")
        return path

    @synchronized
    def pending_draft_hash(self, draft_id):
        """Return the verified body hash of an uncommitted creation, if present."""
        if not self.root or draft_id not in self.directories:
            return None
        directory = self._directory(draft_id)
        pending = directory / ".save-pending.json"
        if not pending.is_file() or is_link(pending):
            return None
        journal = load_json(pending)
        name = journal.get("new_file")
        if journal.get("id") != draft_id or journal.get("old_file") is not None:
            return None
        if not isinstance(name, str) or Path(name).name != name or Path(name).suffix not in (".md", ".txt"):
            return None
        body = directory / name
        if is_link(body) or not body.is_file():
            return None
        raw = body.read_bytes()
        actual = digest(raw.decode("utf-8-sig"))
        return actual if matches_body_snapshot(raw, journal.get("new_hash")) else None

    @synchronized
    def read(self, entry_id):
        record = deepcopy(self.records[entry_id])
        try:
            record["body"] = normalize_body(self._body_path(record).read_text(encoding="utf-8-sig")
                                            if self.root else self.memory[entry_id][record["file"]])
        except (OSError, UnicodeError) as error:
            raise DiaryError("正文无法读取；请恢复文件或修复编码") from error
        record["hash"] = digest(record["body"])
        return record

    @synchronized
    def metadata(self, kind=None):
        """Newest-first active descriptor copies, without reading body files."""
        self.refresh()
        return sorted((deepcopy(record) for record in self.records.values()
                       if not record.get("deleted") and (kind is None or record["kind"] == kind)),
                      key=lambda record: (record["date"], record["updated_at"]), reverse=True)

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
    def save(self, fields, entry_id=None, expected_hash=None, *, draft_id=None):
        fields = deepcopy(fields)
        try:
            fields["date"] = date.fromisoformat(fields["date"]).isoformat()
            if fields["kind"] not in KINDS or fields.get("format", ".md") not in (".md", ".txt"):
                raise ValueError()
            if not all(isinstance(fields[key], str) for key in ("title", "body")):
                raise ValueError()
            fields["body"] = normalize_body(fields["body"])
            if not isinstance(fields.get("tags", []), list) or any(not isinstance(tag, str) for tag in fields.get("tags", [])):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as error:
            raise DiaryError("请检查日期、正文和格式") from error
        if not entry_id and draft_id:
            if not re.fullmatch(r"[0-9a-f]{32}", draft_id):
                raise DiaryError("无效草稿标识")
            self.refresh()
            if draft_id in self.records:
                entry_id = draft_id
        if entry_id:
            self.refresh()
            old = self.read(entry_id)
            if expected_hash is not None and old["hash"] != expected_hash:
                raise Conflict("外部文件已修改；你的编辑仍保留，请先处理冲突")
            record = deepcopy(self.records[entry_id])
        else:
            entry_id = draft_id or uuid4().hex
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
        if record["kind"] != "diary":
            record["versions"].append({"file": filename, "at": record["updated_at"],
                                       "title": record["title"], "date": record["date"], "metadata": metadata})
        if self.root:
            existing_diary = record["kind"] == "diary" and entry_id in self.records
            directory = (self._directory(entry_id) if existing_diary else
                         self._dated_directory(entry_id, record["date"]) if record["kind"] == "diary"
                         else self._directory(entry_id))
            diary = record["kind"] == "diary"
            if diary:
                atomic_json(directory / ".save-pending.json", {
                    "id": entry_id, "old_file": old["file"] if existing_diary else None, "new_file": filename,
                    "old_hash": old["hash"] if existing_diary else None, "new_hash": digest(fields["body"]),
                    "record": record if not existing_diary else None,
                })
            atomic_text(directory / filename, fields["body"])
            # Descriptor is the only commit point. Failed commits preserve the old pointer.
            try:
                atomic_json(directory / "record.json", record)
            except BaseException:
                if existing_diary:
                    self._recover_save(directory, self.records[entry_id])
                elif diary:
                    self._recover_uncommitted_creation(directory)
                    if (directory / "record.json").exists():
                        self.records[entry_id] = record
                        result = deepcopy(record)
                        result.update(body=fields["body"], hash=digest(fields["body"]))
                        return result
                else:
                    (directory / filename).unlink(missing_ok=True)
                raise
            if diary:
                self.records[entry_id] = record
                try:
                    directory = self._recover_save(directory, record)
                    self.directories[entry_id] = directory.name
                except (OSError, DiaryError):
                    # The descriptor already committed. Recovery is retried on refresh.
                    pass
                result = deepcopy(record)
                result.update(body=fields["body"], hash=digest(fields["body"]))
                return result
        else:
            if record["kind"] == "diary":
                self.memory[entry_id] = {}
            self.memory.setdefault(entry_id, {})[filename] = fields["body"]
        self.records[entry_id] = record
        return self.read(entry_id)

    @synchronized
    def migrate_diary(self, entry_id):
        """Remove recorded obsolete revisions after validating the committed body."""
        self.refresh()
        record = deepcopy(self.records[entry_id])
        if record["kind"] != "diary":
            raise DiaryError("只能迁移日记")
        self.read(entry_id)
        old_files = set()
        for version in record["versions"]:
            name = version.get("file")
            if not isinstance(name, str) or Path(name).name != name or Path(name).suffix not in (".md", ".txt"):
                raise DiaryError("历史正文路径无效")
            path = self._directory(entry_id) / name
            if is_link(path):
                raise DiaryError("历史正文不允许链接跳转")
            if name != record["file"]:
                old_files.add(name)
        directory = self._dated_directory(entry_id, record["date"])
        for name in old_files:
            (directory / name).unlink(missing_ok=True)
        record["versions"] = []
        atomic_json(directory / "record.json", record)
        self.records[entry_id] = record
        return len(old_files)

    @synchronized
    def acknowledge_generation(self, entry_id):
        """Clear a saved generation's recovery marker without creating a text revision."""
        self.refresh()
        record = deepcopy(self.records[entry_id])
        record["provenance"].pop("pending_coverage", None)
        if self.root:
            atomic_json(self._directory(entry_id) / "record.json", record)
        self.records[entry_id] = record

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
