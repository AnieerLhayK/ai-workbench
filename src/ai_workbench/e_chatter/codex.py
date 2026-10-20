"""Isolated stdio client. Host owns history, tools, copies and all durable writes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time

from .files import ChatterError
from . import VERSION
from .. import codex_isolation as isolation


SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "reply": {"type": "string"}, "status": {"type": "string", "enum": ["needs_input", "completed"]},
    "files": {"type": "array", "items": {"type": "object", "additionalProperties": False,
              "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    "diagnosis": {"type": "string"}, "handoff": {"type": "string"}, "build_intake": {"type": "string"}},
    "required": ["reply", "status", "files", "diagnosis", "handoff", "build_intake"]}


def argv(executable, *args):
    path = Path(executable)
    if path.suffix.lower() in (".cmd", ".ps1"):
        script = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = str(path.parent / "node.exe") if (path.parent / "node.exe").is_file() else shutil.which("node")
        if not node or not script.is_file():
            raise ChatterError("无法解析 Codex npm 入口，请选择 codex.exe 或完整 npm 安装入口")
        return [node, str(script), *args]
    return [str(path), *args]


def executable():
    return shutil.which("codex.exe") or shutil.which("codex.cmd") or shutil.which("codex")


def reply_prefix(raw):
    """Expose only the JSON reply string, never proposal bytes or raw protocol."""
    match = re.search(r'"reply"\s*:\s*"', raw)
    if not match:
        return ""
    text = raw[match.end():]
    escaped = False
    for index, char in enumerate(text):
        if char == '"' and not escaped:
            text = text[:index]
            break
        escaped = char == "\\" and not escaped
    while text:
        try:
            return json.loads('"' + text + '"')
        except ValueError:
            text = text[:-1]
    return ""


class Rpc:
    def __init__(self, command, directory, *, env=None, label="Codex", jsonrpc=False):
        self.label, self.jsonrpc = label, jsonrpc
        self.process = subprocess.Popen(command, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=env)
        self.lock = threading.RLock()
        self.pending = {}
        self.events = {}
        self.sequence = 0
        self.closed = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        def drain():
            for _ in self.process.stderr:
                pass
        self.drain = threading.Thread(target=drain, daemon=True)
        self.drain.start()

    def _send(self, message):
        with self.lock:
            if self.closed or self.process.poll() is not None:
                raise ChatterError(f"{self.label} 连接已关闭")
            self.process.stdin.write(json.dumps(({"jsonrpc": "2.0"} if self.jsonrpc else {}) | message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "method" in message:
                    if "id" in message:
                        # No model-initiated write, permission escalation or external tool can be approved.
                        self._send({"id": message["id"], "error": {"code": -32601, "message": "This application does not expose execution or write tools"}})
                    params = message.get("params") or {}
                    thread = params.get("threadId") or params.get("sessionId") or params.get("thread", {}).get("id")
                    with self.lock:
                        if "_all" in self.events:
                            self.events["_all"].put(message)
                        if thread:
                            self.events.setdefault(thread, queue.Queue()).put(message)
                else:
                    with self.lock:
                        waiter = self.pending.get(message.get("id"))
                    if waiter:
                        waiter.put(message)
        finally:
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put(None)
                for events in self.events.values():
                    events.put(None)

    def request(self, method, params, timeout=45, cancelled=None):
        with self.lock:
            self.sequence += 1
            request_id = self.sequence
            self.pending[request_id] = waiter = queue.Queue()
        try:
            self._send({"id": request_id, "method": method, "params": params})
            try:
                deadline = time.monotonic() + timeout
                while True:
                    if cancelled is not None and cancelled.is_set():
                        raise ChatterError("请求已取消")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise queue.Empty()
                    try:
                        message = waiter.get(timeout=min(.2, remaining))
                        break
                    except queue.Empty:
                        continue
            except queue.Empty as error:
                raise ChatterError(f"{self.label} 请求超时，可重试连接") from error
            if message is None:
                code = self.process.poll()
                if code is None:
                    try:
                        code = self.process.wait(timeout=.2)
                    except subprocess.TimeoutExpired:
                        pass
                detail = f"（退出码 {code}）" if code is not None else ""
                raise ChatterError(f"{self.label} 连接提前结束{detail}，请刷新连接后重试")
            if "error" in message:
                # Protocol error bodies can contain host configuration; don't expose/persist them.
                raise ChatterError(f"{self.label} 不支持当前请求：{method}（{message['error'].get('code', 'unknown')}）")
            return message["result"]
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=8)
        self.closed = True
        self.reader.join(5)
        self.drain.join(5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


class Codex:
    def __init__(self, directory, cli=None):
        self.directory = Path(directory)
        self.cli = cli or executable()
        self.rpc = None
        self.lock = threading.RLock()
        self.models = []

    def connect(self):
        with self.lock:
            if self.rpc and self.rpc.process.poll() is None:
                return self.rpc
            if not self.cli:
                raise ChatterError("未找到本机 Codex，请先安装，或在设置中选择已有入口")
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                catalog_path = isolation.catalog(self.cli, self.directory, argv)
            except isolation.IsolationError as error:
                raise ChatterError(str(error)) from error
            command = argv(self.cli, "--no-daemon", "app-server", "--listen", "stdio://")
            command += isolation.options(catalog_path)
            rpc = Rpc(command, self.directory)
            try:
                rpc.request("initialize", {"clientInfo": {"name": "e_chatter", "title": "e-Chatter", "version": VERSION}})
                rpc._send({"method": "initialized", "params": {}})
                config = rpc.request("config/read", {"includeLayers": False})["config"]
                overrides = isolation.mcp_overrides(config)
                if overrides:
                    rpc.close()
                    command += overrides
                    rpc = Rpc(command, self.directory)
                    rpc.request("initialize", {"clientInfo": {"name": "e_chatter", "title": "e-Chatter", "version": VERSION}})
                    rpc._send({"method": "initialized", "params": {}})
                    config = rpc.request("config/read", {"includeLayers": False})["config"]
                isolation.verify_config(config)
                self.models = []
                cursor = None
                while True:
                    models = rpc.request("model/list", {"cursor": cursor} if cursor else {})
                    self.models += [{"id": m["id"], "name": m.get("displayName", m["id"]), "default": m.get("isDefault", False),
                                     "efforts": [{"id": e["reasoningEffort"], "name": e.get("description") or e["reasoningEffort"]} for e in m.get("supportedReasoningEfforts", [])],
                                     "default_effort": m.get("defaultReasoningEffort")} for m in models.get("data", [])]
                    cursor = models.get("nextCursor")
                    if not cursor:
                        break
            except isolation.IsolationError as error:
                rpc.close()
                raise ChatterError(str(error)) from error
            except BaseException:
                rpc.close()
                raise
            self.rpc = rpc
            return rpc

    def account(self):
        result = self.connect().request("account/read", {"refreshToken": False})
        account = result.get("account")
        return {"connected": bool(account), "label": account.get("email") or account.get("type", "Codex") if account else "未登录 Codex", "models": self.models}

    def login(self):
        result = self.connect().request("account/login/start", {"type": "chatgpt"})
        return {"url": result.get("authUrl"), "login_id": result.get("loginId")}

    def authenticate(self, action, **values):
        if action == "login":
            return self.login()
        if action == "logout":
            self.connect().request("account/logout", {})
            return {"pending": False}
        if action == "cancel" and values.get("login_id"):
            self.connect().request("account/login/cancel", {"loginId": values["login_id"]})
            return {"pending": False}
        raise ChatterError("当前 Codex 不支持该认证操作")

    def generate(self, request, cancelled, emit):
        rpc = self.connect()
        policy_root = Path(__file__).with_name("resources")
        policy = (policy_root / "policy.md").read_text(encoding="utf-8")
        role = request["payload"]["role"]
        if role != "chat":
            policy += "\n\n" + (policy_root / "skills" / role / "SKILL.md").read_text(encoding="utf-8")
        result = rpc.request("thread/start", {"cwd": str(self.directory), "ephemeral": True, "sandbox": "read-only",
                                             "approvalPolicy": "never", "model": request.get("model"),
                                             "baseInstructions": policy, "developerInstructions": policy})
        thread_id = result["thread"]["id"]
        if request.get("execution") is not None:
            actual = result.get("model") or result["thread"].get("model")
            if actual:
                request["execution"]["actual_model"] = actual
            # Thread defaults do not describe the later turn's explicit effort.
        with rpc.lock:
            events = rpc.events.setdefault(thread_id, queue.Queue())
        turn = rpc.request("turn/start", {"threadId": thread_id,
                                         "effort": request.get("execution", {}).get("effort"),
                                         "input": [{"type": "text", "text": json.dumps(request["payload"], ensure_ascii=False)}],
                                         "outputSchema": SCHEMA})["turn"]
        chunks, final = {}, ""
        deadline = time.monotonic() + 900
        interrupted = False
        try:
            while time.monotonic() < deadline:
                if cancelled.is_set():
                    rpc.request("turn/interrupt", {"threadId": thread_id, "turnId": turn["id"]}, timeout=10)
                    interrupted = True
                    raise ChatterError("生成已取消，未保存不完整结果")
                try:
                    event = events.get(timeout=.2)
                except queue.Empty:
                    continue
                if event is None:
                    raise ChatterError("Codex 连接中断，已有记录已保留")
                method, params = event["method"], event.get("params") or {}
                if method == "item/agentMessage/delta":
                    item_id = params.get("itemId", "reply")
                    chunks[item_id] = chunks.get(item_id, "") + params["delta"]
                    emit(reply_prefix(chunks[item_id]))
                if method == "item/completed":
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage":
                        final = item.get("text", "") or final
                if isolation.is_tool_event(params):
                    try:
                        rpc.request("turn/interrupt", {"threadId": thread_id, "turnId": turn["id"]}, timeout=10)
                    except ChatterError:
                        self.close()
                    finally:
                        interrupted = True
                    raise ChatterError("模型触发了应用范围之外的工具，结果未提交")
                if method == "turn/completed":
                    if params["turn"]["status"] != "completed":
                        raise ChatterError("Codex 未完成请求，请检查登录、额度和模型配置")
                    result = json.loads(final or next(reversed(chunks.values()), ""))
                    result["provider_thread_id"] = thread_id
                    return result
            raise ChatterError("Codex 生成超时，已有记录已保留")
        finally:
            if not interrupted:
                try:
                    rpc.request("thread/unsubscribe", {"threadId": thread_id}, timeout=5)
                except ChatterError:
                    pass
            with rpc.lock:
                rpc.events.pop(thread_id, None)

    def close(self):
        if self.rpc:
            self.rpc.close()
            self.rpc = None


class DemoCodex:
    def __init__(self, agent="codex"):
        self.agent = agent

    def account(self):
        return {"connected": True, "label": "演示模式", "models": [{"id": "demo", "name": "演示模型", "default": True, "efforts": [{"id": "low", "name": "低"}, {"id": "high", "name": "高"}]}]}

    def authenticate(self, action, **values):
        raise ChatterError("演示模式不操作账号或凭据")

    def generate(self, request, cancelled, emit):
        role = request["payload"]["role"]
        text = "这是内存演示回复。真实模式会使用你的 Codex 和所加载的角色资源。"
        result = dict(reply=text, status="completed", files=[], diagnosis="", handoff="", build_intake="")
        if role == "doctor":
            result.update(reply="演示诊断已保存：可检查表达节奏与情绪直白程度。", diagnosis="# 演示诊断\n\n目标是示例角色的选定回复；这不是实际模型诊断。", handoff="# 演示交接\n\n建议 Maintainer 检查表达方式，保留原有事实。")
        elif role == "maintainer":
            skill = request["payload"]["character"].get("SKILL.md", "")
            result.update(reply="已准备角色副本修改，请审阅。", files=[{"path": "SKILL.md", "content": skill + "\nLet emotions emerge from concrete details rather than direct declarations.\n"}])
        elif role == "generator":
            result.update(reply="已准备示例新角色，请审阅后保存。", files=[{"path": "SKILL.md", "content": "---\nname: new-demo-character\ndescription: Synthetic character for explicit demo only.\n---\n\nWrite original, restrained prose; retain supplied facts.\n"}])
        for end in range(1, len(result["reply"]) + 1, 2):
            if cancelled.wait(.015):
                raise ChatterError("演示生成已取消")
            emit(result["reply"][:end + 1])
        return result

    def close(self):
        pass
