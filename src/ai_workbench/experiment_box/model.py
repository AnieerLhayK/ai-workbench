"""Trial storage Module: validated snapshots, atomic commit, no implicit recovery."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from contextlib import contextmanager
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import uuid4

from ..storage import atomic_json, ProcessLock

STATUSES = ("待开始", "试验中", "暂停", "已完成")
TEXT_FIELDS = ("name", "source", "goal", "directory", "command", "next_action", "status")
FIELD_LABELS = {"name": "名称", "source": "来源链接", "goal": "试验目标", "directory": "工作目录",
                "command": "PowerShell 命令", "next_action": "下一步", "status": "状态", "tags": "标签"}
REQUEST_LABELS = {"applied": "已保存", "pending": "待你确认", "conflict": "版本冲突", "rejected": "已拒绝",
                  "cancelled": "已取消", "approved": "已批准", "running": "运行中", "finished": "执行结束", "failed": "执行失败"}


class StoreError(ValueError):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def trial_fields(values):
    if not isinstance(values, dict) or any(not isinstance(values.get(key), str) for key in TEXT_FIELDS):
        raise StoreError("试验字段格式不完整")
    result = {key: values[key].strip() for key in TEXT_FIELDS}
    if not result["name"]:
        raise StoreError("请填写试验名称")
    if result["status"] not in STATUSES:
        raise StoreError("未知试验状态")
    if result["source"]:
        try:
            parsed = urlparse(result["source"])
        except ValueError as error:
            raise StoreError("来源链接须为完整的 HTTP(S) 地址") from error
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise StoreError("来源链接须为完整的 HTTP(S) 地址")
    tags = values.get("tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise StoreError("标签格式错误")
    result["tags"] = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    return result


def validate_time(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise StoreError("记录时间格式错误")


def validate_document(value):
    if not isinstance(value, dict) or value.get("version") not in (1, 2) or not isinstance(value.get("trials"), list):
        raise StoreError("不支持的试验数据格式")
    ids = set()
    for trial in value["trials"]:
        trial_fields(trial)
        if not isinstance(trial.get("id"), str) or not trial["id"] or trial["id"] in ids:
            raise StoreError("试验标识损坏或重复")
        ids.add(trial["id"])
        validate_time(trial.get("created_at"))
        validate_time(trial.get("updated_at"))
        if not isinstance(trial.get("records"), list):
            raise StoreError("试验记录格式错误")
        for record in trial["records"]:
            if not isinstance(record, dict) or any(not isinstance(record.get(key), str) for key in ("result", "next_action", "at")):
                raise StoreError("结果记录格式错误")
            validate_time(record["at"])
            if not isinstance(record.get("paths"), list) or any(not isinstance(path, str) for path in record["paths"]):
                raise StoreError("关联文件路径格式错误")
    selected = value.get("selected_id")
    if selected is not None and (not isinstance(selected, str) or selected not in ids):
        raise StoreError("选中试验不存在")
    if value["version"] == 2:
        if not isinstance(value.get("revision"), int) or not isinstance(value.get("requests"), dict) or not isinstance(value.get("conversations"), dict):
            raise StoreError("版本与请求记录损坏")
        for trial in value["trials"]:
            if not isinstance(trial.get("revision"), int) or trial["revision"] < 1:
                raise StoreError("试验版本损坏")
        for request_id, receipt in value["requests"].items():
            if (not isinstance(receipt, dict) or receipt.get("request_id") != request_id
                    or receipt.get("status") not in {"pending", "applied", "conflict", "rejected", "cancelled", "approved", "running", "finished", "failed"}
                    or not isinstance(receipt.get("operations"), list) or not isinstance(receipt.get("base"), dict)):
                raise StoreError("请求历史损坏")
            if (not receipt["operations"] or not isinstance(receipt.get("fingerprint"), str)
                    or receipt.get("origin") not in ("cli", "assistant")
                    or not isinstance(receipt.get("plan_hash"), str)
                    or not isinstance(receipt.get("summary"), list)
                    or any(not isinstance(s, str) for s in receipt["summary"])
                    or not isinstance(receipt.get("versions"), dict)):
                raise StoreError("请求历史字段损坏")
            validate_time(receipt.get("at"))
            if receipt["status"] not in ("rejected", "conflict"):
                for op in receipt["operations"]:
                    validate_operation(op, receipt["base"], ids)
            if receipt["status"] in ("approved", "running", "finished"):
                validate_time(receipt.get("approved_at"))
                if len(receipt["operations"]) != 1 or receipt["operations"][0].get("action") != "plan":
                    raise StoreError("执行请求损坏")
        for messages in value["conversations"].values():
            if not isinstance(messages, list):
                raise StoreError("对话记录损坏")
            for message in messages:
                if (not isinstance(message, dict) or message.get("role") not in ("user", "assistant", "error")
                        or not isinstance(message.get("text"), str)):
                    raise StoreError("对话记录损坏")
                validate_time(message.get("at"))
    return value


def validate_operation(op, base, ids):
    if not isinstance(op, dict) or op.get("action") not in ("create", "update", "observe", "plan"):
        raise StoreError("操作历史损坏")
    action = op["action"]
    if action != "create":
        trial_id = op.get("trial_id")
        if (not isinstance(trial_id, str) or trial_id not in ids or type(op.get("expected_version")) is not int
                or not isinstance(base.get(trial_id), dict) or type(base[trial_id].get("revision")) is not int):
            raise StoreError("操作版本历史损坏")
    if action in ("create", "update"):
        fields = op.get("fields")
        if (not isinstance(fields, dict) or not fields or set(fields) - ({*TEXT_FIELDS, "tags"} - {"directory", "command"})
                or any(not isinstance(v, str) for k, v in fields.items() if k != "tags")
                or ("tags" in fields and (not isinstance(fields["tags"], list) or any(not isinstance(t, str) for t in fields["tags"])))):
            raise StoreError("操作字段历史损坏")
    elif action == "observe":
        if (any(not isinstance(op.get(k), str) for k in ("result", "next_action"))
                or not isinstance(op.get("references"), list) or any(not isinstance(p, str) for p in op["references"])):
            raise StoreError("观察历史损坏")
    else:
        if (op.get("runtime") not in ("python", "powershell")
                or any(not isinstance(op.get(k), str) for k in ("goal", "script"))
                or type(op.get("timeout_seconds")) is not int or not 1 <= op["timeout_seconds"] <= 300
                or not isinstance(op.get("files"), list)
                or any(not isinstance(f, dict) or any(not isinstance(f.get(k), str) for k in ("path", "content")) for f in op["files"])
                or not isinstance(base[op["trial_id"]].get("files"), dict)):
            raise StoreError("计划历史损坏")


class TrialStore:
    """All callers read copies; state changes only after the writer succeeds."""
    def __init__(self, path: Path | None, *, writer=atomic_json):
        self.path, self.writer = path, writer
        self.persisted = bool(path is not None and path.exists())
        self.document = {"version": 1, "selected_id": None, "trials": []}
        if path is not None and path.exists():
            try:
                self.document = validate_document(json.loads(path.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise StoreError("试验数据无法读取；原文件已保留，请检查或恢复备份") from error

    def reload(self):
        if self.path and self.persisted and not self.path.exists():
            raise StoreError("试验数据文件已丢失；请检查原文件或备份，未重建数据")
        if self.path and self.path.exists():
            try:
                self.document = validate_document(json.loads(self.path.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise StoreError("试验数据无法读取；原文件已保留，请检查或恢复备份") from error

    @contextmanager
    def transaction(self):
        lock = None
        try:
            if self.path:
                deadline = time.monotonic() + 5
                while True:
                    lock = ProcessLock(self.path.with_suffix(".write.lock"))
                    if lock.acquired:
                        break
                    if time.monotonic() >= deadline:
                        raise StoreError("其他进程正在保存，请稍后重试")
                    time.sleep(.025)
                self.reload()
            value = self.snapshot()
            if value["version"] == 1:
                if self.path and self.path.exists():
                    backup = self.path.with_name("trials.v1.backup.json")
                    if backup.exists() and backup.read_bytes() != self.path.read_bytes():
                        backup = self.path.with_name("trials.v1.backup-" + str(uuid4()) + ".json")
                    if not backup.exists():
                        with backup.open("xb") as stream:
                            stream.write(self.path.read_bytes())
                value.update(version=2, revision=0, requests={}, conversations={})
                for trial in value["trials"]:
                    trial["revision"] = 1
            yield value
            if value == self.document:
                return
            value["revision"] += 1
            self._commit(value)
        except OSError as error:
            raise StoreError("保存失败；编辑内容仍保留，请检查数据目录") from error
        finally:
            if lock:
                lock.close()

    def snapshot(self):
        return deepcopy(self.document)

    def _commit(self, value):
        validate_document(value)
        if self.path is not None:
            try:
                self.writer(self.path, value)
            except OSError as error:
                raise StoreError("保存失败；编辑内容仍保留，请检查数据目录") from error
        self.document = value
        self.persisted = bool(self.path and self.path.exists())

    def _find(self, value, trial_id):
        for trial in value["trials"]:
            if trial["id"] == trial_id:
                return trial
        raise StoreError("试验不存在")

    def save(self, fields, trial_id=None, expected=None):
        fields = trial_fields(fields)
        if expected is None:
            expected = self._find(self.document, trial_id).get("revision", 1) if trial_id else None
        with self.transaction() as value:
            now = timestamp()
            if trial_id is None:
                trial_id = str(uuid4())
                value["trials"].append(dict(fields, id=trial_id, revision=1, created_at=now, updated_at=now, records=[]))
            else:
                trial = self._find(value, trial_id)
                if trial["revision"] != expected:
                    raise StoreError("试验已更新；请重新核对，草稿已保留")
                trial.update(fields, updated_at=now, revision=expected + 1)
            self._find(value, trial_id)["records"].append(dict(result="人工新建" if expected is None else "人工编辑", next_action=fields["next_action"], paths=[], at=now, origin="human", kind="change"))
            value["selected_id"] = trial_id
        return trial_id

    def select(self, trial_id):
        if self.document["selected_id"] == trial_id:
            return
        with self.transaction() as value:
            if trial_id is not None:
                self._find(value, trial_id)
            value["selected_id"] = trial_id

    def record(self, trial_id, result, next_action, paths, expected=None):
        if not isinstance(result, str) or not result.strip():
            raise StoreError("请填写试验结果")
        if not isinstance(next_action, str) or not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise StoreError("结果字段格式错误")
        with self.transaction() as value:
            trial = self._find(value, trial_id)
            if expected is not None and trial["revision"] != expected:
                raise StoreError("试验已更新；请重新核对，草稿已保留")
            now = timestamp()
            trial["records"].append(dict(result=result.strip(), next_action=next_action.strip(), paths=[p.strip() for p in paths if p.strip()], at=now, origin="human"))
            trial.update(next_action=next_action.strip(), updated_at=now, revision=trial["revision"] + 1)

    def trials(self, query="", status="全部"):
        query = query.strip().casefold()
        return [trial for trial in self.snapshot()["trials"]
                if (status == "全部" or trial["status"] == status)
                and query in " ".join([trial["name"], *trial["tags"]]).casefold()]


def demo_store():
    store = TrialStore(None)
    for name, status, goal, next_action, tags in (
        ("Pi 登录验证", "待开始", "验证登录和一次模型调用", "完成浏览器授权", ["AI", "试验"]),
        ("Commander 连接试验", "试验中", "测试与 Commander 的连接", "检查已有设备连接", ["工具", "连接"]),
        ("本地脚本试验", "暂停", "运行本地脚本并检查输出", "准备一个无副作用的样例", ["脚本", "本地"]),
    ):
        store.save(dict(name=name, status=status, goal=goal, next_action=next_action, tags=tags,
                        source="https://github.com/earendil-works/pi" if name.startswith("Pi") else "",
                        directory=str(Path.cwd()), command="pi" if name.startswith("Pi") else "Write-Output 'demo'"))
    store.select(store.document["trials"][0]["id"])
    return store
