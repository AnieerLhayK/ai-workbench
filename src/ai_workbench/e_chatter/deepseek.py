"""Dedicated, tool-free official Harness profile. No desktop credentials are read."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import time

import yaml

from .codex import Rpc, SCHEMA, reply_prefix
from . import VERSION
from .files import ChatterError, atomic, plain_path, uid


SAFE_ROWS = {"sdk-app-startup", "deepseek-llm-api-extensions", "llm-deepseek", "sandbox", "filesystem", "attachment-local", "working-directory", "session-projection", "token-meter", "compaction-basic", "image-offload", "sandbox-policy", "timer", "llm", "session", "session-title", "system-prompt", "tools", "agent", "llm-retry", "jobs", "agent-loop", "sessions"}


def installation(entry=None):
    path = Path(entry) if entry else Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DeepSeek Harness/DeepSeek Harness.exe"
    if path.name.lower() == "dsh.cmd" and path.parent.name == "bin":
        path = path.parents[4] / "DeepSeek Harness.exe"
    if path.name != "DeepSeek Harness.exe" or not path.is_file():
        raise ChatterError("请选择官方 DeepSeek Harness.exe 或其自带的 dsh.cmd；旧 pilot 入口不受支持")
    return plain_path(path)


class DeepSeek:
    def __init__(self, root, cli=None, auth="account"):
        self.root, self.cli, self.auth = Path(root), cli, auth
        self.control = None
        self.lock = threading.RLock()
        self.jobs = set()

    def _open(self, role="chat", cancelled=None):
        if cancelled is not None and cancelled.is_set():
            raise ChatterError("生成已取消")
        exe = installation(self.cli)
        self.root.mkdir(parents=True, exist_ok=True)
        directory = self.root / "runs" / uid()
        directory.mkdir(parents=True)
        modules = exe.parent / "resources/app.asar/dsh/node_modules"
        # A fresh profile/home for every process prevents inherited patches and plugins.
        home = directory / "home"
        profile = home / "profiles/sdk-minimal"
        manifest = {"name": "e-chatter-private-profile", "private": True, "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-sdk-minimal"]}}}
        atomic(profile / "package.json", json.dumps(manifest).encode())
        atomic(profile / "cordis.patch.yml", b"[]\n")
        policy = (Path(__file__).with_name("resources") / "policy.md").read_text(encoding="utf-8")
        if role != "chat":
            policy += "\n" + (Path(__file__).with_name("resources") / "skills" / role / "SKILL.md").read_text(encoding="utf-8")
        policy += "\nReturn exactly one JSON object, no markdown fences, matching: " + json.dumps(SCHEMA)
        bridge = Path(__file__).with_name("resources") / "harness-bridge.mjs"
        # Explicit known template roster. Unknown template rows are refused by the
        # runtime version check below rather than inherited into a new deployment.
        from .harness_archive import read_file
        version = json.loads(read_file(exe.parent / "resources/app.asar", "package.json"))["version"]
        if version != "0.2.1-rc.2":
            raise ChatterError("Harness 版本尚未验证隔离兼容性；当前支持 0.2.1-rc.2")
        bundle = yaml.load(read_file(exe.parent / "resources/app.asar", "dsh/node_modules/@deepseek-ai/dsh-sdk-minimal/cordis.patch.yml"), Loader=yaml.BaseLoader)
        rows = bundle[0]["insert"]
        known = SAFE_ROWS | {"sdk-jsonrpc-server", "session-log-deepseek", "plugin-package-inventory-deepseek", "tool-fs", "tool-working-directory", "subprocess", "pty", "terminal-bash", "terminal-pwsh", "persistent-bash", "persistent-pwsh", "mcp-resources"}
        if {r["id"] for r in rows} != known:
            raise ChatterError("Harness 模板能力已变化，隔离检查未通过")
        patch = [{"id": r["id"], "disabled": r["id"] not in SAFE_ROWS} for r in rows]
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

    def connect(self):
        with self.lock:
            if not self.control or self.control.process.poll() is not None:
                self.control = self._open()
            return self.control

    def account(self):
        value = self.connect().request("e-chatter/status", {})
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
            rpc.close()
