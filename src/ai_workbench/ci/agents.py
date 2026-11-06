"""Native coding entrypoints; credentials and default models stay with each harness."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import uuid

from ..storage import atomic_json
from .service import CIError


class NativeAgent:
    def __init__(self, environment=None):
        self.environment = environment

    def _context(self, workspace, settings):
        workspace = Path(workspace).resolve(strict=True)
        runtime = workspace.parent / ("native-" + uuid.uuid4().hex)
        runtime.mkdir()
        temp = runtime / "temp"
        temp.mkdir()
        base = Path(settings.get("skill_path") or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills" / "gh-fix-ci")
        if base.is_file():
            base = base.parent
        roots = []
        required = ("SKILL.md", "LICENSE.txt", "agents/openai.yaml", "scripts/inspect_pr_checks.py", "assets/github-small.svg", "assets/github.png")
        for location in ("skills/gh-fix-ci", ".agents/skills/gh-fix-ci", ".claude/skills/gh-fix-ci"):
            target = runtime / location
            for relative in required:
                source = base / relative
                if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024:
                    raise CIError("请配置已安装 gh-fix-ci 的目录或 SKILL.md 路径")
                (target / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target / relative)
            roots.append(str(target))
        policy = {"workspace": str(workspace), "skill": roots[0], "skill_roots": roots, "repository": settings["repository"], "test_command": settings["test_command"]}
        atomic_json(runtime / "policy.json", policy)
        env = dict(self.environment or os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", TMP=str(temp), TEMP=str(temp))
        return runtime, env

    def _process(self, command, cwd, env, prompt, timeout=600):
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            stdout, _ = process.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if os.name == "nt" and process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
            else:
                process.kill()
            process.communicate(timeout=15)
            raise CIError("Agent 超过十分钟限制，已停止本次执行") from error
        if process.returncode:
            raise CIError("原生 agent 执行失败，请在原生入口检查登录和运行环境")
        events = []
        for line in stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        return events

    def run(self, workspace, prompt, settings):
        runtime, env = self._context(workspace, settings)
        agent = settings["agent"]
        prompt += f"\nThe private clone is {str(workspace)!r}. Set every command's working directory to this clone. Runtime skills are read-only."
        if agent == "dsh":
            from .dsh import execute
            return execute(workspace, runtime, env, settings, prompt)
        if agent == "claude":
            executable = shutil.which("claude") or shutil.which("claude.cmd")
            if not executable:
                raise CIError("Claude Code 原生入口不存在")
            hook = subprocess.list2cmdline([sys.executable, "-B", str(Path(__file__).with_name("tool_guard.py")), str(runtime / "policy.json")])
            atomic_json(runtime / "claude-overlay.json", {"hooks": {"PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": hook, "timeout": 15}]}]}})
            command = [executable, "--print", "--verbose", "--output-format", "stream-json", "--no-session-persistence", "--permission-mode", "acceptEdits", "--add-dir", str(workspace), "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--settings", str(runtime / "claude-overlay.json"), "--allowedTools", "Read,Edit,Write,Glob,Grep,Skill,Bash,PowerShell,TodoWrite", "--disallowedTools", "WebFetch,WebSearch,Task,Agent,NotebookEdit"]
            if settings.get("model"):
                command += ["--model", settings["model"]]
            events = self._process(command, runtime, env, prompt)
            calls = set()
            loaded = False
            for event in events:
                content = event.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for item in content:
                    if item.get("type") == "tool_use" and item.get("name") == "Skill" and item.get("input", {}).get("skill") == "gh-fix-ci":
                        calls.add(item.get("id"))
                    if item.get("type") == "tool_result" and item.get("tool_use_id") in calls and not item.get("is_error", False):
                        loaded = True
            completed = any(event.get("type") == "result" and not event.get("is_error") for event in events)
        elif agent == "codex":
            executable = shutil.which("codex") or shutil.which("codex.cmd")
            if not executable:
                raise CIError("Codex 原生入口不存在")
            command = [executable, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "workspace-write", "-C", str(runtime), "--add-dir", str(workspace), "-c", 'approval_policy="never"', "-c", 'web_search="disabled"', "-c", "sandbox_workspace_write.network_access=false", "-c", "features.multi_agent=false"]
            if os.name == "nt":
                command += ["-c", 'windows.sandbox="' + settings.get("codex_windows_sandbox", "unelevated") + '"']
            home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            if (home / "config.toml").is_file():
                config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
                for name in config.get("mcp_servers", {}):
                    if not name.replace("_", "").replace("-", "").isalnum():
                        raise CIError("Codex MCP 配置名尚不支持安全覆盖")
                    command += ["-c", f"mcp_servers.{name}.enabled=false"]
            if settings.get("model"):
                command += ["--model", settings["model"]]
            command += ["-"]
            events = self._process(command, runtime, env, prompt)
            loaded = any(event.get("type") == "item.completed" and event.get("item", {}).get("type") == "command_execution" and event["item"].get("exit_code") == 0 and "gh-fix-ci" in event["item"].get("command", "") and "Gh Pr Checks Plan Fix" in event["item"].get("aggregated_output", "") for event in events)
            completed = any(event.get("type") == "turn.completed" for event in events)
        else:
            template = settings.get("agent_commands", {}).get(agent)
            if not isinstance(template, list) or not template or any(not isinstance(value, str) for value in template):
                raise CIError("自定义 agent 尚未配置命令 argv")
            prompt_file = runtime / "prompt.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            values = {"workspace": str(workspace), "prompt_file": str(prompt_file), "model": settings.get("model", "")}
            events = self._process([value.format_map(values) for value in template], runtime, env, prompt)
            completed = any(event.get("completed") is True for event in events)
            loaded = any(event.get("skill_loaded") is True for event in events)
        if not completed or not loaded:
            raise CIError("未取得原生完成和 gh-fix-ci 加载回执；不判为成功")
        actual_model = next((event.get("model") for event in events if event.get("type") == "system" and event.get("subtype") == "init"), None)
        return {"completed": True, "skill_loaded": True, "agent": agent, "model": actual_model, "requested_model": settings.get("model", "")}

    def verify(self, workspace, command, settings):
        backend = settings.get("verification_agent", settings["agent"] if settings["agent"] in ("dsh", "codex") else "dsh")
        if backend == "codex":
            executable = shutil.which("codex") or shutil.which("codex.cmd")
            if not executable:
                raise CIError("缺少独立 Codex 沙箱验证入口")
            arguments = [executable, "sandbox", "--permission-profile", ":workspace", "-C", str(workspace)]
            if os.name == "nt":
                arguments += ["-c", 'windows.sandbox="' + settings.get("codex_windows_sandbox", "unelevated") + '"']
            return subprocess.run([*arguments, *command], cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        if backend != "dsh":
            raise CIError("未配置可用的独立沙箱验证器")
        runtime, env = self._context(workspace, settings)
        from .dsh import execute
        return execute(workspace, runtime, env, settings, verify=command)
