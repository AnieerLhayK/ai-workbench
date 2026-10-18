"""Local Codex Adapter: stdio history reads and isolated noninteractive generation."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from .library import DiaryError
from .. import codex_isolation as isolation


class RpcError(DiaryError):
    """Protocol detail stays in memory; callers expose only safe categories."""
    def __init__(self, method, error):
        self.code = error.get("code")
        self.detail = error.get("message", "")
        super().__init__(f"Codex 历史 Interface 不可用：{method}；请检查 CLI 版本")


def argv(executable, *arguments):
    path = Path(executable)
    if path.suffix.lower() in (".cmd", ".ps1"):
        # npm's PowerShell wrapper can buffer pipeline input until EOF. JSON-RPC
        # needs a bidirectional stream, so launch its existing Node entry directly.
        script = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        local_node = path.parent / "node.exe"
        node = str(local_node) if local_node.is_file() else shutil.which("node")
        if not script.is_file() or not node:
            raise DiaryError("无法解析 Codex npm 入口；请选择已有 codex.exe 或完整 npm 安装入口")
        return [node, str(script), *arguments]
    return [str(path), *arguments]


def popen(command, cwd):
    return subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def terminate(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        else:
            process.kill()
        process.wait(timeout=15)


def drain(stream):
    for _ in stream:
        pass


class AppServer:
    def __init__(self, executable, cwd, cancelled=None, *, options=(), client_name="e_diary", experimental=False):
        self.process = popen(argv(executable, "app-server", "--stdio", *options), cwd)
        self.cancelled = cancelled or threading.Event()
        self.messages = queue.Queue()
        self.sequence = 0
        def read():
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
            self.messages.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        # Drain diagnostics without persisting private provider output.
        self.diagnostics = threading.Thread(target=drain, args=(self.process.stderr,), daemon=True)
        self.diagnostics.start()
        try:
            self.request("initialize", {"clientInfo": {"name": client_name, "version": "1.0.0"},
                                        "capabilities": {"experimentalApi": experimental}})
            self.process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
            self.process.stdin.flush()
        except Exception:
            self.close()
            raise

    def send_request(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        return request_id

    def request(self, method, params, timeout=45, *, on_poll=None):
        request_id = self.send_request(method, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if on_poll:
                on_poll()
            if self.cancelled.is_set():
                raise DiaryError("任务已取消")
            try:
                message = self.messages.get(timeout=.2)
            except queue.Empty:
                continue
            if message is None:
                raise DiaryError("Codex 历史连接已结束；请检查本机 CLI")
            if message.get("id") == request_id:
                if "error" in message:
                    raise RpcError(method, message["error"])
                return message["result"]
        raise DiaryError("Codex 历史读取超时")

    def close(self):
        terminate(self.process)
        self.reader.join(timeout=5)
        self.diagnostics.join(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "title": {"type": "string"}, "body": {"type": "string"},
        "files": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                  "properties": {"name": {"type": "string"}, "content": {"type": "string"}},
                  "required": ["name", "content"]}}},
    "required": ["title", "body", "files"]}


class CodexAdapter:
    def __init__(self, config):
        self.config = config

    def generate(self, prompt, directory, cancelled, progress):
        if cancelled.is_set():
            raise DiaryError("任务已取消")
        schema = directory / "response-schema.json"
        schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
        result_path = directory / "response.json"
        try:
            command = isolation.exec_command(self.config["codex_cli"], argv, directory, schema, result_path,
                policy="You are e-Diary's isolated writing task. Use only supplied evidence. Do not invoke tools or access files or external services. Return the required JSON.",
                model=self.config.get("model"))
        except isolation.IsolationError as error:
            raise DiaryError(str(error)) from error
        if cancelled.is_set():
            raise DiaryError("任务已取消；未提交材料")
        process = popen(command, directory)
        thread_ids = []
        unsafe = threading.Event()
        def read_events():
            for line in process.stdout:
                try:
                    event = json.loads(line)
                    if isolation.is_tool_event(event):
                        unsafe.set()
                    if event.get("type") == "thread.started":
                        thread_ids.append(event["thread_id"])
                except (ValueError, KeyError):
                    pass
        reader = threading.Thread(target=read_events, daemon=True)
        diagnostics = threading.Thread(target=drain, args=(process.stderr,), daemon=True)
        reader.start()
        diagnostics.start()
        try:
            process.stdin.write(prompt)
            process.stdin.close()
            deadline = time.monotonic() + self.config.get("generation_timeout_seconds", 900)
            while process.poll() is None:
                if unsafe.is_set():
                    raise DiaryError("Codex 触发范围外工具，未保存结果")
                if cancelled.wait(.2):
                    raise DiaryError("任务已取消")
                if time.monotonic() >= deadline:
                    raise DiaryError("Codex 生成超时，可在任务窗口重试")
            if process.returncode:
                raise DiaryError(f"Codex 生成失败（退出码 {process.returncode}），请检查登录、额度与配置")
            reader.join(timeout=5)
            diagnostics.join(timeout=5)
            if reader.is_alive() or diagnostics.is_alive():
                raise DiaryError("Codex 输出尚未结束，未提交不完整结果")
            if unsafe.is_set():
                raise DiaryError("Codex 触发范围外工具，未保存结果")
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            result["thread_ids"] = thread_ids
            return result
        finally:
            terminate(process)
            reader.join(timeout=5)
            diagnostics.join(timeout=5)
            for stream in (process.stdout, process.stderr):
                stream.close()


class DemoAdapter:
    def generate(self, prompt, directory, cancelled, progress):
        if cancelled.wait(.15):
            raise DiaryError("任务已取消")
        return {"title": "这段时间的记录", "body": "这是一份演示总结。真实模式会依据所选时期的日记、会话和项目记录生成正文，并保留可查看的来源。\n\n演示内容不代表你的实际状态。", "files": []}
