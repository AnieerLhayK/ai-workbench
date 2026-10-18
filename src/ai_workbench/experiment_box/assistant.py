"""Ephemeral, tool-free Codex proposals; host applies validated operations."""
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from ..e_diary.codex import argv, popen, terminate, drain
from .. import codex_isolation as isolation
from .model import StoreError, REQUEST_LABELS

SHORTCUTS = {
    "@新建试验": "新建一项试验：目标是……，先整理目标、标签和下一步。",
    "@完善试验": "根据当前记录完善试验内容，列出缺失信息；核心目标变更请提出审批。",
    "@更新进展": "更新本轮进展：……。记录为观察，整理下一步。",
    "@设计试验": "为当前目标设计一轮离线 Python 或 PowerShell 验证，列出拟改文件、完整脚本和预期证据，时限 300 秒。",
    "@总结结果": "总结已有观察和程序实际结果，说明证据与不足，提出下一步；不要自行标记完成。",
}


def object_schema(properties):
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


STRING = {"type": "string"}
FIELDS = object_schema({key: STRING for key in ("name", "source", "goal", "next_action", "status")} | {"tags": {"type": "array", "items": STRING}})
# Optional changes use a field/value list. Convert to the public service envelope
# only after response validation; never allow the model to choose provenance.
CHANGE = object_schema({"field": {"type": "string", "enum": ["name", "source", "goal", "next_action", "status", "tags"]}, "value": STRING})
OP = object_schema({"action": {"type": "string", "enum": ["create", "update", "observe", "plan"]},
                    "trial_id": STRING, "expected_version": {"type": "integer"},
                    "changes": {"type": "array", "items": CHANGE}, "result": STRING, "next_action": STRING,
                    "references": {"type": "array", "items": STRING}, "goal": STRING,
                    "runtime": {"type": "string", "enum": ["python", "powershell"]}, "script": STRING,
                    "files": {"type": "array", "items": object_schema({"path": STRING, "content": STRING})},
                    "timeout_seconds": {"type": "integer"}})
SCHEMA = object_schema({"reply": STRING, "operations": {"type": "array", "items": OP}})


def operations(result):
    if not isinstance(result, dict) or set(result) != {"reply", "operations"} or not isinstance(result["reply"], str) or not isinstance(result["operations"], list):
        raise StoreError("助手响应格式错误，未写入提案")
    converted = []
    for item in result["operations"]:
        if not isinstance(item, dict) or set(item) != set(OP["properties"]):
            raise StoreError("助手操作格式错误")
        action = item["action"]
        op = {"action": action}
        if action != "create":
            op.update(trial_id=item["trial_id"], expected_version=item["expected_version"])
        if action in ("create", "update"):
            fields = {}
            for change in item["changes"]:
                if not isinstance(change, dict) or set(change) != {"field", "value"} or change["field"] in fields:
                    raise StoreError("助手字段重复或格式错误")
                value = change["value"]
                if not isinstance(value, str):
                    raise StoreError("助手字段须为文本")
                if change["field"] == "tags":
                    try:
                        value = json.loads(value) if value.lstrip().startswith("[") else value.replace("，", ",").split(",")
                    except ValueError as error:
                        raise StoreError("助手标签格式错误") from error
                    if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
                        raise StoreError("助手标签须为文本列表")
                fields[change["field"]] = value
            op["fields"] = fields
        elif action == "observe":
            op.update({k: item[k] for k in ("result", "next_action", "references")})
        elif action == "plan":
            op.update({k: item[k] for k in ("goal", "runtime", "script", "files", "timeout_seconds")})
        else:
            raise StoreError("助手提出了范围外操作")
        converted.append(op)
    return converted


class CodexAssistant:
    def __init__(self, config):
        self.config = config
        self.phase = "尚未请求"

    def generate(self, payload, directory, cancelled):
        if cancelled.is_set():
            raise StoreError("生成已取消")
        policy = Path(__file__).with_name("assistant_policy.md").read_text(encoding="utf-8")
        schema, output = (directory / name for name in ("schema.json", "response.json"))
        schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
        try:
            command = isolation.exec_command(self.config["codex_cli"], argv, directory, schema, output,
                policy=policy, model=self.config.get("model", "gpt-6.1-sol"), images=payload.get("images", []), reasoning="low")
        except isolation.IsolationError as error:
            raise StoreError(str(error)) from error
        payload = {key: value for key, value in payload.items() if key != "images"}
        if cancelled.is_set():
            raise StoreError("生成已取消；未启动模型请求")
        process = popen(command, directory)
        self.phase = "请求已启动"
        unsafe = threading.Event()
        def read():
            for line in process.stdout:
                try:
                    event = json.loads(line)
                    self.phase = event.get("type", "等待响应")
                    if isolation.is_tool_event(event):
                        unsafe.set()
                except ValueError:
                    pass
        readers = [threading.Thread(target=read, daemon=True), threading.Thread(target=drain, args=(process.stderr,), daemon=True)]
        for reader in readers:
            reader.start()
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False))
            process.stdin.close()
            deadline = time.monotonic() + 300
            while process.poll() is None:
                if cancelled.wait(.1) or unsafe.is_set() or time.monotonic() > deadline:
                    raise StoreError("生成已取消、超时或触发能力检查；未提交提案")
            for reader in readers:
                reader.join(5)
            if process.returncode or unsafe.is_set() or any(r.is_alive() for r in readers):
                raise StoreError("Codex 生成失败；请检查版本、登录与额度，未保存不完整提案")
            result = json.loads(output.read_text(encoding="utf-8-sig"))
            operations(result)
            return result
        finally:
            terminate(process)
            for reader in readers:
                reader.join(5)
            process.stdout.close()
            process.stderr.close()


class AssistantJobs(QObject):
    changed = Signal(str)
    finished = Signal(str, str, object)
    def __init__(self, service, adapter=None, parent=None):
        super().__init__(parent)
        self.service, self.adapter = service, adapter
        self.cancelled = threading.Event()
        self.pending = False
        self.thread = None
        self.delivery = None
        self.failed_result = False
        self.closing = False
        self.finished.connect(self._finish)

    def send(self, context, text, materials=()):
        if self.failed_result:
            raise StoreError("上一轮结果尚未保存，请先重试保存")
        if self.pending or self.adapter is None:
            return False
        self.service.reload()
        snapshot = self.service.snapshot()
        trial = next((t for t in snapshot["trials"] if t["id"] == context), None)
        payload = dict(user=text, context=context, trials=snapshot["trials"] if context == "overview" else [trial],
                       conversation=snapshot.get("conversations", {}).get(context, [])[-30:], materials=list(materials))
        labels = [Path(m["value"]).name if m["type"] == "file" else m["value"] for m in materials]
        self.service.chat(context, "user", text + ("\n本轮附加资料：\n" + "\n".join(labels) if labels else ""))
        self.pending = True
        self.delivery = None
        self.context = context
        self.cancelled = threading.Event()
        cancelled = self.cancelled
        def work():
            try:
                directory = self.service.root / "generation" / str(uuid4())
                directory.mkdir(parents=True)
                from .materials import prepare
                payload["materials"], payload["images"] = prepare(materials, directory)
                result = self.adapter.generate(payload, directory, cancelled)
                self.finished.emit(context, "", result if not cancelled.is_set() else None)
            except Exception as error:
                self.finished.emit(context, str(error) if isinstance(error, StoreError) else "助手请求失败，草稿和已有记录已保留", None)
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self.changed.emit(context)
        return True

    def _finish(self, context, error, result):
        if self.closing:
            return
        self.pending = False
        if self.cancelled.is_set():
            error, result = "生成已取消", None
        if result:
            try:
                proposals = operations(result)
            except (StoreError, ValueError, KeyError, TypeError) as failure:
                error, result = "助手响应无效，未提交提案：" + str(failure), None
        try:
            if result:
                if self.delivery is None:
                    self.delivery = dict(context=context, result=result, request_id=str(uuid4()), reply_saved=False, status_saved=False)
                if not self.delivery["reply_saved"]:
                    self.service.chat(context, "assistant", result["reply"])
                    self.delivery["reply_saved"] = True
                if proposals:
                    receipt = self.service.submit(dict(request_id=self.delivery["request_id"], operations=proposals), origin="assistant",
                                                  context=None if context == "overview" else context)
                    if not self.delivery["status_saved"]:
                        self.service.chat(context, "assistant", "提案状态：" + REQUEST_LABELS[receipt["status"]] + (" · " + receipt["error"] if "error" in receipt else ""))
                        self.delivery["status_saved"] = True
                self.failed_result = False
            elif error:
                self.service.chat(context, "error", error)
        except (StoreError, ValueError, TypeError, KeyError) as failure:
            self.failed_result = result is not None
            self.changed.emit("保存失败：" + str(failure))
        self.changed.emit(context)

    def cancel(self):
        self.cancelled.set()

    def retry_save(self):
        if self.failed_result and self.delivery:
            self._finish(self.delivery["context"], "", self.delivery["result"])

    def close(self):
        if self.failed_result:
            raise StoreError("助手结果尚未保存；请先点击重试保存，再关闭窗口")
        self.closing = True
        self.cancel()
        if self.thread:
            self.thread.join(5)
        if self.pending:
            try:
                self.service.chat(self.context, "error", "窗口关闭，生成已取消；未应用未完成的提案")
            except StoreError:
                pass
            self.pending = False
