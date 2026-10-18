"""Transactional installation-local records; Codex credentials never enter here."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading

from .files import ChatterError, plain_path, uid


TABLES = ("folders", "sessions", "messages", "characters", "versions", "tasks", "proposals", "records")


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Document rows share one transaction boundary and stable IDs."""
    def __init__(self, root: Path | None):
        self.root = plain_path(Path(root)) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.depth = 0
        self.db = sqlite3.connect(str(self.root / "chatter.sqlite") if self.root else ":memory:", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS documents (kind TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(kind,id))")
            self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        self.put_setting("theme", self.setting("theme", "light"))
        self.put_setting("characters_root", self.setting("characters_root", str(self.root / "characters") if self.root else "演示模式 / characters"))
        # Interrupted provider turns are never reclassified as completed.
        with self.transaction():
            for task in self.rows("tasks"):
                if task["status"] == "running":
                    self.update("tasks", task["id"], status="interrupted", error="上次运行中断，可重新发送")

    @contextmanager
    def transaction(self):
        with self.lock:
            outer = self.depth == 0
            if outer:
                self.db.execute("BEGIN IMMEDIATE")
            self.depth += 1
            try:
                yield
                if outer:
                    self.db.commit()
            except BaseException:
                if outer:
                    self.db.rollback()
                raise
            finally:
                self.depth -= 1

    def rows(self, kind):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM documents WHERE kind=? ORDER BY rowid", (kind,))]

    def get(self, kind, record_id):
        with self.lock:
            row = self.db.execute("SELECT body FROM documents WHERE kind=? AND id=?", (kind, record_id)).fetchone()
            if not row:
                raise ChatterError("记录不存在，请刷新后重试")
            return json.loads(row[0])

    def add(self, table, **values):
        value = {"id": uid(), "created_at": now(), **values}
        with self.transaction():
            self.db.execute("INSERT INTO documents VALUES (?,?,?)", (table, value["id"], json.dumps(value, ensure_ascii=False)))
        return value

    def update(self, table, record_id, **values):
        with self.transaction():
            value = self.get(table, record_id) | values
            self.db.execute("UPDATE documents SET body=? WHERE kind=? AND id=?", (json.dumps(value, ensure_ascii=False), table, record_id))
        return value

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put_setting(self, key, value):
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def snapshot(self):
        with self.lock:
            return {kind: self.rows(kind) for kind in TABLES} | {"settings": {key: json.loads(value) for key, value in self.db.execute("SELECT key,value FROM settings")}}

    def close(self):
        self.db.close()
