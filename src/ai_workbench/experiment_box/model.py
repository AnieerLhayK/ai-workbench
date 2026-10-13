"""Trial storage Module: validated snapshots, atomic commit, no implicit recovery."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from ..storage import atomic_json

STATUSES = ("待开始", "试验中", "暂停", "已完成")
TEXT_FIELDS = ("name", "source", "goal", "directory", "command", "next_action", "status")


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
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("trials"), list):
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
    return value


class TrialStore:
    """All callers read copies; state changes only after the writer succeeds."""
    def __init__(self, path: Path | None, *, writer=atomic_json):
        self.path, self.writer = path, writer
        self.document = {"version": 1, "selected_id": None, "trials": []}
        if path is not None and path.exists():
            try:
                self.document = validate_document(json.loads(path.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise StoreError("试验数据无法读取；原文件已保留，请检查或恢复备份") from error

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

    def _find(self, value, trial_id):
        for trial in value["trials"]:
            if trial["id"] == trial_id:
                return trial
        raise StoreError("试验不存在")

    def save(self, fields, trial_id=None):
        fields = trial_fields(fields)
        value = self.snapshot()
        now = timestamp()
        if trial_id is None:
            trial_id = str(uuid4())
            value["trials"].append(dict(fields, id=trial_id, created_at=now, updated_at=now, records=[]))
        else:
            self._find(value, trial_id).update(fields, updated_at=now)
        value["selected_id"] = trial_id
        self._commit(value)
        return trial_id

    def select(self, trial_id):
        if self.document["selected_id"] == trial_id:
            return
        value = self.snapshot()
        self._find(value, trial_id)
        value["selected_id"] = trial_id
        self._commit(value)

    def record(self, trial_id, result, next_action, paths):
        if not isinstance(result, str) or not result.strip():
            raise StoreError("请填写试验结果")
        if not isinstance(next_action, str) or not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise StoreError("结果字段格式错误")
        value = self.snapshot()
        trial = self._find(value, trial_id)
        now = timestamp()
        trial["records"].append(dict(result=result.strip(), next_action=next_action.strip(), paths=[p.strip() for p in paths if p.strip()], at=now))
        trial.update(next_action=next_action.strip(), updated_at=now)
        self._commit(value)

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
