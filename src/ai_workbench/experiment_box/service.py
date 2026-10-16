"""Application authority: proposals, revisions, provenance and human decisions."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
from uuid import uuid4

from .model import StoreError, TEXT_FIELDS, FIELD_LABELS, timestamp, trial_fields
from ..storage import ProcessLock


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
        raise StoreError("标识必须为应用内 ID")
    return value


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 240:
        raise StoreError("文件引用须为应用内相对路径")
    parts = value.replace("\\", "/").split("/")
    if (PureWindowsPath(value).drive or value.startswith(("/", "\\"))
            or any(p in ("", ".", "..") or ":" in p or p.endswith((" ", ".")) for p in parts)
            or any(re.match(r"(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)", p) for p in parts)):
        raise StoreError("拒绝外部路径、父目录或特殊设备引用")
    return "/".join(parts)


def confined(root, reference):
    root = Path(root).absolute()
    result = root.joinpath(*relative(reference).split("/"))
    for candidate in (root, *root.parents, result, *result.parents):
        if candidate.exists() or candidate.is_symlink():
            if candidate.is_symlink() or getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400:
                raise StoreError("拒绝符号链接或重解析目录")
    if not result.resolve().is_relative_to(root.resolve()):
        raise StoreError("引用超出试验目录")
    return result


def manifest(root):
    """Bounded, non-following inventory of one app-owned trial, never host roots."""
    files = {}
    if not root.exists():
        return files
    confined(root, "scope-check")
    size = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in [*dirs, *names]:
            path = confined(root, Path(directory, name).relative_to(root).as_posix())
            if path.is_file():
                size += path.stat().st_size
                if size > 8_000_000 or len(files) >= 200:
                    raise StoreError("试验目录超过首版范围：最多 200 文件 / 8 MB")
                files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


class ExperimentService:
    """UI uses manual methods; untrusted JSON has only submit/read capabilities.

    Human methods are intentionally absent from the external CLI dispatch table.
    Like any same-user desktop app this is not an OS boundary against a hostile
    owner who directly edits its private JSON or imports Python internals.
    """
    def __init__(self, store, root=None):
        self.store = store
        self.root = Path(root) if root else None

    def snapshot(self):
        return self.store.snapshot()

    def trials(self, *args):
        return self.store.trials(*args)

    def reload(self):
        self.store.reload()
        if not self.root:
            return
        for request_id, receipt in self.snapshot().get("requests", {}).items():
            if receipt["status"] not in ("running", "approved"):
                continue
            if receipt["status"] == "approved" and (datetime.now(timezone.utc) - datetime.fromisoformat(receipt["approved_at"])).total_seconds() < 30:
                continue
            lock = ProcessLock(self.worker_lock_path(request_id))
            if not lock.acquired:
                continue
            try:
                with self.store.transaction() as doc:
                    current = doc["requests"].get(request_id)
                    if not current or current["status"] not in ("running", "approved"):
                        continue
                    self._interrupted(doc, current, "worker_lost", "执行工作进程已中断；实际退出码与输出未知，未自动重试")
            finally:
                lock.close()

    def worker_lock_path(self, request_id):
        return confined(self.root, "workers/" + identifier(request_id) + ".lock")

    def _interrupted(self, doc, receipt, reason, message):
        execution = dict(interruption=reason)
        receipt.update(status="failed", ended_at=timestamp(), execution=execution, error=message)
        trial = self.store._find(doc, receipt["operations"][0]["trial_id"])
        trial["records"].append(dict(at=timestamp(), origin="runner", kind="execution",
                                     request_id=receipt["request_id"], result=message,
                                     next_action=trial["next_action"], paths=[], execution=execution))
        trial.update(revision=trial["revision"] + 1, updated_at=timestamp())

    def fail_launch(self, request_id):
        with self.store.transaction() as doc:
            receipt = doc["requests"].get(identifier(request_id))
            if receipt and receipt["status"] == "approved":
                self._interrupted(doc, receipt, "launch_failed", "工作进程未能启动；未自动重试，请重新提交计划")

    def work_root(self, trial_id):
        if not self.root:
            raise StoreError("演示模式不访问本机试验目录")
        return confined(self.root, "trials/" + identifier(trial_id) + "/work")

    def select(self, trial_id):
        self.store.select(trial_id)

    def save(self, fields, trial_id=None, expected=None):
        """Explicit manual form submission is itself a human decision."""
        trial_id = self.store.save(fields, trial_id, expected)
        return trial_id

    def record(self, *args):
        self.store.record(*args)

    def submit(self, request, *, origin="cli", context=None):
        if origin not in ("cli", "assistant"):
            raise StoreError("无效的提案来源")
        if not isinstance(request, dict) or set(request) != {"request_id", "operations"}:
            raise StoreError("请求只允许 request_id 和 operations")
        request_id = identifier(request["request_id"])
        operations = request["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= 20:
            raise StoreError("每次提交 1 至 20 个操作")
        fingerprint = digest(request)
        with self.store.transaction() as doc:
            previous = doc["requests"].get(request_id)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise StoreError("请求 ID 已被其他内容使用")
                return deepcopy(previous)
            receipt = dict(request_id=request_id, fingerprint=fingerprint, origin=origin,
                           status="pending", at=timestamp(), operations=deepcopy(operations),
                           summary=[], versions={}, base={}, plan_hash="")
            try:
                critical = len(operations) > 1
                for op in operations:
                    critical |= self._validate(doc, op, receipt, context)
                receipt["plan_hash"] = digest({"operations": operations, "base": receipt["base"]})
                if not critical:
                    self._apply(doc, receipt)
                receipt["summary"] = [op["action"] + ": " + op.get("trial_id", op.get("fields", {}).get("name", "新建")) for op in operations]
            except StoreError as error:
                receipt.update(status="conflict" if "版本冲突" in str(error) else "rejected", error=str(error))
            doc["requests"][request_id] = receipt
        return deepcopy(receipt)

    def _validate(self, doc, op, receipt, context):
        if not isinstance(op, dict) or op.get("action") not in ("create", "update", "observe", "plan"):
            raise StoreError("仅允许新建、更新、观察记录和本地试验计划")
        action = op["action"]
        allowed = {"create": {"action", "fields"}, "update": {"action", "trial_id", "expected_version", "fields"},
                   "observe": {"action", "trial_id", "expected_version", "result", "next_action", "references"},
                   "plan": {"action", "trial_id", "expected_version", "goal", "runtime", "script", "files", "timeout_seconds"}}[action]
        if set(op) != allowed:
            raise StoreError("操作字段不完整或包含越权字段")
        trial = None
        if action != "create":
            trial_id = identifier(op["trial_id"])
            if context is not None and context != trial_id:
                raise StoreError("助手只能修改本次对话的试验")
            trial = self.store._find(doc, trial_id)
            if type(op["expected_version"]) is not int or op["expected_version"] != trial["revision"]:
                raise StoreError("版本冲突；请重新读取试验并核对")
            receipt["base"][trial_id] = {"revision": trial["revision"]}
        elif context is not None:
            raise StoreError("请在总览中新建试验")
        if action in ("create", "update"):
            fields = op["fields"]
            if not isinstance(fields, dict) or not fields or set(fields) - ({*TEXT_FIELDS, "tags"} - {"directory", "command"}):
                raise StoreError("CLI／助手不能设置外部目录或人工终端命令")
            defaults = dict.fromkeys(TEXT_FIELDS, "") | {"status": "待开始", "tags": []}
            checked = trial_fields((trial or defaults) | fields)
            marking_complete = checked["status"] == "已完成" and (trial is None or trial["status"] != "已完成")
            return marking_complete or bool(trial and "goal" in fields and checked["goal"] != trial["goal"])
        if action == "observe":
            if not isinstance(op["result"], str) or not op["result"].strip() or not isinstance(op["next_action"], str) or not isinstance(op["references"], list):
                raise StoreError("观察记录格式错误")
            for reference in op["references"]:
                relative(reference)
            return False
        if op["runtime"] not in ("python", "powershell") or not isinstance(op["goal"], str) or not op["goal"].strip():
            raise StoreError("首版仅支持 Python／PowerShell 本地脚本")
        if type(op["timeout_seconds"]) is not int or not 1 <= op["timeout_seconds"] <= 300:
            raise StoreError("运行时限必须为 1 至 300 秒")
        script = relative(op["script"])
        if Path(script).suffix.lower() != (".py" if op["runtime"] == "python" else ".ps1"):
            raise StoreError("脚本扩展名与运行环境不一致")
        files = op["files"]
        if not isinstance(files, list) or len(files) > 20:
            raise StoreError("最多提出 20 个文本文件变更")
        names, size = set(), 0
        for file in files:
            if not isinstance(file, dict) or set(file) != {"path", "content"} or not isinstance(file["content"], str):
                raise StoreError("拟改文件格式错误")
            name = relative(file["path"])
            if name.casefold() in names:
                raise StoreError("重复文件引用")
            names.add(name.casefold())
            size += len(file["content"].encode("utf-8"))
            confined(self.work_root(trial["id"]), name)
        if size > 200_000:
            raise StoreError("计划文件超过 200 KB")
        before = manifest(self.work_root(trial["id"]))
        if script.casefold() not in names and script not in before:
            raise StoreError("计划缺少可运行脚本")
        receipt["base"][trial["id"]]["files"] = before
        return True

    def _apply(self, doc, receipt):
        for op in receipt["operations"]:
            action, now = op["action"], timestamp()
            if action == "create":
                fields = trial_fields(dict.fromkeys(TEXT_FIELDS, "") | {"status": "待开始", "tags": []} | op["fields"])
                trial = dict(fields, id=str(uuid4()), revision=1, created_at=now, updated_at=now, records=[])
                doc["trials"].append(trial)
            else:
                trial = self.store._find(doc, op["trial_id"])
                if action == "update":
                    trial.update(trial_fields(trial | op["fields"]))
                if action == "observe":
                    trial["records"].append(dict(result=op["result"], next_action=op["next_action"], paths=op["references"], at=now, origin=receipt["origin"], kind="observation"))
                    trial["next_action"] = op["next_action"]
                trial["revision"] += 1
                trial["updated_at"] = now
            summary = {"create": "新建试验", "update": "更新试验", "observe": "追加观察", "plan": "提出试验计划"}[action]
            if action == "update":
                summary += "\n" + "\n".join(FIELD_LABELS[key] + "：" + ("、".join(value) if isinstance(value, list) else value) for key, value in op["fields"].items())
            trial["records"].append(dict(result=summary, next_action=trial["next_action"], paths=[], at=now,
                                         origin=receipt["origin"], request_id=receipt["request_id"], kind="change"))
            receipt["versions"][trial["id"]] = trial["revision"]
        receipt["status"] = "applied"

    def decide(self, request_id, plan_hash, *, approve):
        """Called only by the native human review component, never JSON dispatch."""
        with self.store.transaction() as doc:
            receipt = doc["requests"].get(identifier(request_id))
            if not receipt or receipt["status"] != "pending" or receipt["plan_hash"] != plan_hash:
                raise StoreError("审批不存在、已消费或计划已变化")
            if not approve:
                receipt["status"] = "cancelled"
            else:
                for trial_id, base in receipt["base"].items():
                    if self.store._find(doc, trial_id)["revision"] != base["revision"] or ("files" in base and manifest(self.work_root(trial_id)) != base["files"]):
                        receipt.update(status="conflict", error="内容或文件已变化，请重新提交并审批")
                        break
                else:
                    plans = [op for op in receipt["operations"] if op["action"] == "plan"]
                    if plans and (len(plans) != 1 or len(receipt["operations"]) != 1):
                        raise StoreError("每次审批只能运行一项独立计划")
                    if plans:
                        receipt.update(status="approved", approved_at=timestamp())
                    else:
                        receipt["approved_at"] = timestamp()
                        self._apply(doc, receipt)
            receipt["decision"] = dict(origin="human", at=timestamp())
        return deepcopy(receipt)

    def cancel_execution(self, request_id):
        """Human GUI cancellation; never part of untrusted operation dispatch."""
        with self.store.transaction() as doc:
            receipt = doc["requests"].get(identifier(request_id))
            if not receipt or receipt["status"] != "running":
                raise StoreError("本轮已结束或尚未开始")
            receipt["cancel_requested"] = True

    def status(self, request_id):
        self.reload()
        receipt = self.snapshot().get("requests", {}).get(identifier(request_id))
        if receipt is None:
            raise StoreError("请求不存在")
        return receipt

    def chat(self, context, role, text):
        if context != "overview":
            identifier(context)
        if role not in ("user", "assistant", "error") or not isinstance(text, str) or len(text) > 100_000:
            raise StoreError("对话格式或大小错误")
        with self.store.transaction() as doc:
            if context != "overview":
                self.store._find(doc, context)
            doc["conversations"].setdefault(context, []).append(dict(role=role, text=text, at=timestamp()))
