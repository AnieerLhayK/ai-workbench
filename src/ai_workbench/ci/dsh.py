"""Tool-capable official DSH SDK transport, separate from generation-only e-Chatter."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import yaml

from ..e_chatter.deepseek import installation
from ..e_chatter.harness_archive import read_file
from .service import CIError


class Connection:
    def __init__(self, command, cwd, env):
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.messages, self.lock, self.sequence = queue.Queue(), threading.Lock(), 0
        self.skill_calls = set()
        self.skill_loaded = False
        threading.Thread(target=self._read, daemon=True).start()

    def send(self, value):
        with self.lock:
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **value}) + "\n")
            self.process.stdin.flush()

    def _read(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "method" in message:
                if "id" in message:
                    if message["method"] == "approval/request":
                        # The immutable tool guard still denies any out-of-scope call.
                        self.send({"id": message["id"], "result": {"outcome": "allowed-once"}})
                    else:
                        self.send({"id": message["id"], "error": {"code": -32601, "message": "No additional authority in CI repair"}})
                event = message.get("params", {}).get("event", {})
                data = event.get("data", {})
                if event.get("type") == "tool/call" and data.get("name") == "skill":
                    try:
                        args = json.loads(data["arguments"]) if isinstance(data.get("arguments"), str) else data.get("arguments", {})
                        if args.get("name") == "gh-fix-ci":
                            self.skill_calls.add(data["callId"])
                    except (ValueError, KeyError):
                        pass
                if event.get("type") == "tool/result":
                    result = data.get("message", {})
                    if result.get("toolCallId") in self.skill_calls and result.get("isError") is False:
                        self.skill_loaded = True
            else:
                self.messages.put(message)
        self.messages.put(None)

    def request(self, method, params, timeout=45):
        self.sequence += 1
        identity = self.sequence
        self.send({"id": identity, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty as error:
                raise CIError("DSH 等待超时") from error
            if result is None:
                raise CIError("DSH 在返回完成回执前退出")
            if result.get("id") == identity:
                if "error" in result:
                    raise CIError("DSH 原生操作未完成")
                return result.get("result")
        raise CIError("DSH 等待超时")

    def close(self):
        try:
            if self.process.poll() is None:
                self.request("shutdown", {}, 10)
                self.process.wait(timeout=10)
        except Exception:
            if self.process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True, timeout=15)
                else:
                    self.process.kill()
                self.process.wait(timeout=15)


def execute(workspace, runtime, env, settings, prompt=None, verify=None):
    executable = installation(settings.get("dsh_executable"))
    archive = executable.parent / "resources/app.asar"
    version = json.loads(read_file(archive, "package.json")).get("version")
    if version != "0.2.1-rc.2":
        raise CIError("DSH 安装版本尚未通过 CI 工具兼容验收")
    modules = executable.parent / "resources/app.asar/dsh/node_modules"
    home, temp = runtime / "home", runtime / "temp"
    home.mkdir(exist_ok=True)
    if os.name == "nt":
        preparation_env = dict(os.environ)
        preparation_env["PSModulePath"] = str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/Modules")
        for index, directory in enumerate((workspace, temp)):
            result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(Path(__file__).with_name("prepare-windows.ps1")), "-Root", str(directory), "-Backup", str(runtime / f"acl-{index}.sddl")], env=preparation_env, capture_output=True, timeout=30)
            if result.returncode:
                raise CIError("无法为当前用户拥有的隔离目录准备 DSH 权限；未扩大其他目录权限")
    original = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    selected = None
    profile = original / "profiles/desktop/cordis.patch.yml"
    if prompt and profile.is_file():
        rows = yaml.load(profile.read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or []
        selected = next((row.get("config") for row in rows if isinstance(row, dict) and row.get("id") == "agent-default-model"), None)
    if prompt and (not selected or not selected.get("provider") or not selected.get("model")):
        raise CIError("无法读取 DSH 原生默认模型；请先在原生入口完成配置")
    if prompt and settings.get("model"):
        selected = {**selected, "model": settings["model"]}
    bridge = Path(__file__).with_name("dsh-bridge.mjs")
    overlay = [{"id": "sdk-jsonrpc-server", "disabled": True}, {"id": "settings", "disabled": True}, {"id": "config-editor", "disabled": True},
               {"id": "credentials", "config": {"dshHome": str(original if prompt else home), "watch": False}},
               {"id": "sandbox-policy", "config": {"mode": "workspace-write", "workspaceRoot": str(workspace)}},
               {"id": "skill-filesystem", "config": {"includeDefaultRoots": False, "customSkillDirs": [str(runtime / "skills")], "watch": False}},
               {"id": "session-persistence-jsonl", "disabled": True},
               {"id": "session-log-deepseek", "disabled": True},
               {"insert": [{"id": "ci-repair-transport", "name": str(bridge), "inject": ["loader"]}]}]
    if selected:
        overlay.append({"id": "agent-default-model", "config": selected})
    patch = runtime / "profile.yml"
    patch.write_text(yaml.safe_dump(overlay), encoding="utf-8")
    environment = dict(env, ELECTRON_RUN_AS_NODE="1", DSH_HOME=str(home), DSH_TELEMETRY_DISABLED="1", DSH_PRIMARY_RUNTIME="", CI_DSH_MODULES=str(modules), CI_PYTHON=sys.executable, CI_GUARD=str(Path(__file__).with_name("tool_guard.py")), CI_POLICY=str(runtime / "policy.json"), CI_WORKSPACE=str(workspace))
    connection = Connection([str(executable), "--expose-internals", str(modules / "@deepseek-ai/dsh-desktop-host/lib/cli.js"), "--profile", "sdk", "--patch", str(patch)], runtime, environment)
    try:
        if verify is not None:
            command = "& " + " ".join("'" + value.replace("'", "''") + "'" for value in verify)
            result = connection.request("ci/verify", {"cwd": str(workspace), "command": command}, 315)
            value = result.get("value", {})
            if result.get("isError") or value.get("exitCode") is None:
                raise CIError("DSH 独立测试未能在原生沙箱中执行")
            return subprocess.CompletedProcess(verify, value["exitCode"], value.get("stdout", {}).get("text", ""), value.get("stderr", {}).get("text", ""))
        preflight = connection.request("ci/preflight", {})
        selection = preflight["selection"]
        if selection.get("provider") == "deepseek-account" and preflight.get("accountStatus") != "credential-stored":
            raise CIError("请先在 DSH 原生入口登录")
        connection.request("initialize", {"provider": selection["provider"], "model": selection["model"], "cwd": str(workspace), "reasoningEffort": selection.get("reasoningEffort"), "approvalRequests": True, "maxTokens": 8192})
        session = "ci-" + runtime.name
        connection.request("session/prompt", {"sessionId": session, "contentBlocks": [{"type": "text", "text": prompt}]})
        connection.request("session/wait", {"sessionId": session}, 600)
        if not connection.skill_loaded:
            raise CIError("DSH 未返回 gh-fix-ci 的成功加载回执")
        return {"completed": True, "skill_loaded": True, "agent": "dsh", "model": selection["model"], "provider": selection["provider"]}
    finally:
        connection.close()
