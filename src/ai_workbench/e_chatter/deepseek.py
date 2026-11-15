"""Dedicated, tool-free official Harness profile. No desktop credentials are read."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import time
import tempfile
import logging

import yaml

from .codex import Rpc, SCHEMA, reply_prefix
from . import VERSION
from .files import ChatterError, atomic, plain_path, uid


SAFE_ROWS = {"sdk-app-startup", "deepseek-llm-api-extensions", "llm-deepseek", "sandbox", "filesystem", "attachment-local", "working-directory", "session-projection", "token-meter", "compaction-basic", "image-offload", "sandbox-policy", "timer", "llm", "session", "session-title", "system-prompt", "tools", "agent", "llm-retry", "jobs", "agent-loop", "sessions", "tool-executor-native"}
MINIMAL_TOOL_ROWS = {"sdk-jsonrpc-server", "session-log-deepseek", "plugin-package-inventory-deepseek", "tool-fs", "tool-working-directory", "subprocess", "pty", "terminal-bash", "terminal-pwsh", "persistent-bash", "persistent-pwsh", "mcp-resources"}
MINIMAL_TOOL_NAMES = {
    "sdk-jsonrpc-server": "@deepseek-ai/dsh-sdk-jsonrpc-server",
    "session-log-deepseek": "@deepseek-ai/dsh-session-log-deepseek",
    "plugin-package-inventory-deepseek": "@deepseek-ai/dsh-plugin-package-inventory-deepseek",
    "tool-fs": "@deepseek-ai/dsh-tool-fs",
    "tool-working-directory": "@deepseek-ai/dsh-tool-working-directory",
    "subprocess": "@deepseek-ai/dsh-subprocess-local",
    "pty": "@deepseek-ai/dsh-terminal",
    "terminal-bash": "@deepseek-ai/dsh-terminal-bash",
    "terminal-pwsh": "@deepseek-ai/dsh-terminal-bash",
    "persistent-bash": "@deepseek-ai/dsh-tool-bash-persistent",
    "persistent-pwsh": "@deepseek-ai/dsh-tool-pwsh-persistent",
    "mcp-resources": "@deepseek-ai/dsh-mcp-resources",
}
SAFE_ROW_NAMES = {
    "sdk-app-startup": "@deepseek-ai/dsh-sdk-app",
    "deepseek-llm-api-extensions": "@deepseek-ai/dsh-deepseek-llm-api-extensions",
    "llm-deepseek": "@deepseek-ai/dsh-llm-deepseek-api-key",
    "sandbox": "@deepseek-ai/dsh-sandbox-local",
    "filesystem": "@deepseek-ai/dsh-fs-local",
    "attachment-local": "@deepseek-ai/dsh-attachment-local",
    "working-directory": "@deepseek-ai/dsh-working-directory",
    "session-projection": "@deepseek-ai/dsh-session-projection",
    "token-meter": "@deepseek-ai/dsh-token-meter",
    "compaction-basic": "@deepseek-ai/dsh-compaction-basic",
    "image-offload": "@deepseek-ai/dsh-compaction-image-offload",
    "sandbox-policy": "@deepseek-ai/dsh-sandbox-policy",
    "timer": "@deepseek-ai/cordis-plugin-timer",
    "llm": "@deepseek-ai/dsh-llm",
    "session": "@deepseek-ai/dsh-session",
    "session-title": "@deepseek-ai/dsh-session-title",
    "system-prompt": "@deepseek-ai/dsh-system-prompt",
    "tools": "@deepseek-ai/dsh-tools",
    "agent": "@deepseek-ai/dsh-agent",
    "llm-retry": "@deepseek-ai/dsh-llm-retry",
    "jobs": "@deepseek-ai/dsh-jobs-local",
    "agent-loop": "@deepseek-ai/dsh-agent-loop",
    "sessions": "@deepseek-ai/dsh-session-persistence-jsonl",
    "tool-executor-native": "@deepseek-ai/dsh-tool-executor-native",
}
NATIVE_ROSTER_NAMES = {
    "tool-executor-native": "@deepseek-ai/dsh-tool-executor-native",
    "session-checkpoint-policy": "@deepseek-ai/dsh-session-checkpoint-policy",
}
ROSTER_NAMES = {**SAFE_ROW_NAMES, **MINIMAL_TOOL_NAMES, **NATIVE_ROSTER_NAMES}
BASE_ROWS = (SAFE_ROWS - {"tool-executor-native"}) | MINIMAL_TOOL_ROWS
NATIVE_ROWS = BASE_ROWS | set(NATIVE_ROSTER_NAMES)
ROSTER_CONTRACTS = (frozenset(BASE_ROWS), frozenset(NATIVE_ROWS))


def qualified_minimal_rows(executable):
    """Validate the reviewed minimal SDK roster contract before launching.

    The official package version is intentionally not authoritative: a DSH
    patch release may keep the same reviewed rostered capabilities.  Any
    added, removed, duplicated or renamed enabled row still stops isolation.
    """
    from .harness_archive import read_file
    archive = Path(executable).parent / "resources/app.asar"
    rows = yaml.load(read_file(archive, "dsh/node_modules/@deepseek-ai/dsh-sdk-minimal/cordis.patch.yml"), Loader=yaml.BaseLoader)[0]["insert"]
    identifiers = [row["id"] for row in rows]
    by_id = {row["id"]: row for row in rows}
    if len(identifiers) != len(by_id) or frozenset(identifiers) not in ROSTER_CONTRACTS:
        raise ChatterError("Harness 模板能力与已验收契约不一致，隔离检查未通过")
    for row_id, expected in ROSTER_NAMES.items():
        if row_id in by_id and by_id[row_id].get("name") != expected:
            raise ChatterError("Harness 模板能力与已验收契约不一致，隔离检查未通过")
    return rows


def installation(entry=None):
    path = Path(entry) if entry else Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DeepSeek Harness/DeepSeek Harness.exe"
    if path.name.lower() == "dsh.cmd" and path.parent.name == "bin":
        path = path.parents[4] / "DeepSeek Harness.exe"
    if path.name != "DeepSeek Harness.exe" or not path.is_file():
        raise ChatterError("请选择官方 DeepSeek Harness.exe 或其自带的 dsh.cmd；旧 pilot 入口不受支持")
    return plain_path(path)


class DeepSeek:
    def __init__(self, root, cli=None, auth="account", *, output_schema=None, writing_policy=None, persist_session=True, transient_root=None):
        self.root, self.cli, self.auth = Path(root), cli, auth
        self.output_schema = output_schema or SCHEMA
        self.writing_policy = writing_policy
        self.persist_session = persist_session
        self.control = None
        self.lock = threading.RLock()
        self.jobs = set()
        self.transient_root = Path(transient_root) if transient_root else None
        self.transient_directories = []

    def _open(self, role="chat", cancelled=None):
        if cancelled is not None and cancelled.is_set():
            raise ChatterError("生成已取消")
        exe = installation(self.cli)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.transient_root:
            self.transient_root.mkdir(parents=True, exist_ok=True)
            transient = tempfile.TemporaryDirectory(prefix="e-diary-dsh-", dir=self.transient_root)
            with self.lock:
                self.transient_directories.append(transient)
            directory = Path(transient.name)
        else:
            directory = self.root / "runs" / uid()
            directory.mkdir(parents=True)
        modules = exe.parent / "resources/app.asar/dsh/node_modules"
        # A fresh profile/home for every process prevents inherited patches and plugins.
        home = directory / "home"
        profile = home / "profiles/sdk-minimal"
        manifest = {"name": "e-chatter-private-profile", "private": True, "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-sdk-minimal"]}}}
        atomic(profile / "package.json", json.dumps(manifest).encode())
        atomic(profile / "cordis.patch.yml", b"[]\n")
        policy = self.writing_policy or (Path(__file__).with_name("resources") / "policy.md").read_text(encoding="utf-8")
        if role != "chat":
            policy += "\n" + (Path(__file__).with_name("resources") / "skills" / role / "SKILL.md").read_text(encoding="utf-8")
        policy += "\nReturn exactly one JSON object, no markdown fences, matching: " + json.dumps(self.output_schema)
        bridge = Path(__file__).with_name("resources") / "harness-bridge.mjs"
        rows = qualified_minimal_rows(exe)
        safe_rows = SAFE_ROWS if self.persist_session else SAFE_ROWS - {"sessions"}
        patch = [{"id": r["id"], "disabled": r["id"] not in safe_rows} for r in rows]
        patch += [{"id": "system-prompt", "config": {"includeHarnessIdentity": False, "includeRuntimeContext": False, "personaPrefix": policy}},
                  {"id": "llm-deepseek", "config": {"apiKeyEnv": "E_CHATTER_DEEPSEEK_KEY", "streamIdleTimeoutMs": 120000}},
                  {"id": "sandbox-policy", "config": {"mode": "read-only", "workspaceRoot": str(directory)}},
                  {"insert": [
                      {"id": "credentials", "name": "@deepseek-ai/dsh-credentials-local", "config": {"path": str(self.root / "credentials.yaml"), "dshHome": str(home), "watch": True}},
                      {"id": "authorization", "name": "@deepseek-ai/dsh-authorization"},
                      {"id": "deepseek-account", "name": "@deepseek-ai/dsh-deepseek-account-platform"},
                      {"id": "webserver", "name": "@deepseek-ai/dsh-host-webserver", "config": {"host": "127.0.0.1", "port": 0}},
                      {"id": "account-llm", "name": "@deepseek-ai/dsh-llm-deepseek-account"},
                      {"id": "e-chatter-bridge", "name": str(bridge), "inject": ["loader"]},
                  ]}]
        overlay = directory / "isolation.yml"
        atomic(overlay, yaml.safe_dump(patch, allow_unicode=True).encode())
        # Do not inherit user credentials, .env discovery roots or arbitrary Node injection.
        env = {k: v for k, v in os.environ.items() if not any(x in k.upper() for x in ("API_KEY", "TOKEN", "SECRET", "NODE_OPTIONS", "DSH_", "ELECTRON_", "E_CHATTER_"))}
        env.update(ELECTRON_RUN_AS_NODE="1", DSH_HOME=str(home), E_CHATTER_DSH_MODULES=str(modules), E_CHATTER_DSH_AUTH=self.auth, E_CHATTER_VERSION=VERSION)
        command = [str(exe), "--expose-internals", str(modules / "@deepseek-ai/dsh-desktop-host/lib/cli.js"), "--profile", "sdk-minimal", "--patch", str(overlay)]
        rpc = Rpc(command, directory, env=env, label="DeepSeek Harness", jsonrpc=True)
        try:
            result = rpc.request("e-chatter/preflight", {}, cancelled=cancelled)
            if result != {"tools": [], "guard": True, "runtime": "e-chatter-dsh-1"}:
                raise ChatterError("Harness 隔离检查未通过")
        except BaseException:
            rpc.close()
            raise
        return rpc

    def connect(self, cancelled=None):
        with self.lock:
            if not self.control or self.control.process.poll() is not None:
                self.control = self._open(cancelled=cancelled)
            return self.control

    def account(self, cancelled=None):
        value = self.connect(cancelled).request("e-chatter/status", {}, cancelled=cancelled)
        models = []
        for index, model in enumerate(value["models"]):
            reasoning = model.get("info", {}).get("reasoning", {}) or {}
            models.append({"id": model["id"], "name": model["name"], "default": index == 0,
                           "efforts": [{"id": e["id"], "name": e.get("label", e["id"])} for e in reasoning.get("efforts", [])], "default_effort": reasoning.get("defaultEffort")})
        return {"connected": value["connected"], "label": "已连接 DeepSeek Harness" if value["connected"] else "未连接 DeepSeek Harness", "models": models, "has_key": value["has_key"], "auth": self.auth, "attempt": value.get("attempt")}

    def authenticate(self, action, **values):
        if action not in ("login", "cancel", "logout", "save_key", "clear_key"):
            raise ChatterError("未知认证操作")
        return self.connect().request("e-chatter/auth", {"action": action, **values})

    def generate(self, request, cancelled, emit):
        rpc = self._open(request["payload"]["role"], cancelled)
        with self.lock:
            self.jobs.add(rpc)
        try:
            rpc.events["_all"] = events = queue.Queue()
            execution = request["execution"]
            params = {"provider": "deepseek-account" if self.auth == "account" else "deepseek-official", "model": execution["model"], "cwd": str(self.root)}
            if execution.get("effort"):
                params["reasoningEffort"] = execution["effort"]
            initialized = rpc.request("initialize", params, cancelled=cancelled)
            if initialized.get("execution"):
                request["execution"]["actual_model"] = initialized["execution"]["model"]
                request["execution"]["actual_effort"] = initialized["execution"].get("effort")
            sid = request["task_id"]
            rpc.request("session/prompt", {"sessionId": sid, "contentBlocks": [{"type": "text", "text": json.dumps(request["payload"], ensure_ascii=False)}]}, cancelled=cancelled)
            done, errors = threading.Event(), []
            def wait():
                try:
                    rpc.request("session/wait", {"sessionId": sid}, timeout=900)
                except ChatterError as error:
                    errors.append(error)
                finally:
                    done.set()
            threading.Thread(target=wait, daemon=True).start()
            final, streamed = "", ""
            while not done.is_set() or not events.empty():
                if cancelled.is_set():
                    raise ChatterError("生成已取消，未保存不完整结果")
                try:
                    event = events.get(timeout=.2)
                except queue.Empty:
                    continue
                if event is None:
                    raise ChatterError("Harness 连接中断")
                params = event.get("params", {})
                if params.get("sessionId") != sid:
                    continue
                if event.get("method") == "e-chatter/delta":
                    streamed += params.get("text", "")
                    emit(reply_prefix(streamed))
                    continue
                fact = params.get("event", {})
                if fact.get("type", "").startswith("tool/") or event.get("method", "").startswith("subagent."):
                    raise ChatterError("Harness 触发了应用范围之外的工具，结果未提交")
                if fact.get("type") == "assistant/message":
                    if fact.get("interrupted") or fact.get("data", {}).get("interrupted"):
                        raise ChatterError("Harness 生成未完成，未保存结果")
                    message = fact.get("message", fact.get("data", {}).get("message", {}))
                    blocks = message.get("content", [])
                    final = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                    actual = message.get("source", {}).get("model")
                    if actual:
                        request["execution"]["actual_model"] = actual
                    emit(reply_prefix(final))
            if errors:
                raise errors[0]
            try:
                return json.loads(final)
            except ValueError as error:
                raise ChatterError("Harness 返回格式无效，未提交结果") from error
        finally:
            rpc.close()
            with self.lock:
                self.jobs.discard(rpc)

    def close(self):
        with self.lock:
            values = [*self.jobs, *([self.control] if self.control else [])]
            self.control = None
        for rpc in values:
            try:
                rpc.close()
            except Exception:
                if self.transient_root is None:
                    raise
                logging.getLogger(__name__).warning("DeepSeek 运行进程关闭失败")
        with self.lock:
            directories, self.transient_directories = self.transient_directories, []
        for directory in directories:
            try:
                directory.cleanup()
            except OSError:
                logging.getLogger(__name__).warning("DeepSeek 暂存运行目录清理失败")
