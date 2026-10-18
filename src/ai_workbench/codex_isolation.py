"""Generation-only Codex capability policy, shared by both local transports.

This module never changes Codex authentication or the generic history/runner
transport. Callers own prompts, schemas, cancellation and application errors.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess


class IsolationError(ValueError):
    """Safe to show: never contains provider diagnostics or host configuration."""


DISABLED = (
    "shell_tool", "unified_exec", "code_mode", "code_mode_host", "apps", "browser_use",
    "browser_use_external", "computer_use", "hooks", "view_image", "image_generation",
    "skill_search", "skill_mcp_dependency_install", "multi_agent", "multi_agent_v2", "collab", "js_repl",
    "memories", "daemon_auto_start", "tool_suggest", "plugins", "remote_plugin", "plugin_sharing",
    "in_app_browser", "browser_annotation_api", "browser_use_full_cdp_access", "enable_mcp_apps",
    "recommended_plugins", "request_permissions_tool", "sleep_tool", "shell_snapshot",
)
TOOL_EVENTS = frozenset(("command_execution", "file_change", "mcp_tool_call", "web_search",
                         "dynamic_tool_call", "commandExecution", "fileChange", "mcpToolCall",
                         "webSearch", "dynamicToolCall"))


def catalog(executable, directory, argv, policy=None):
    """Obtain only bundled metadata and write a tool-free app-owned catalog."""
    try:
        result = subprocess.run(argv(executable, "debug", "models", "--bundled"),
                                capture_output=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError("unsupported catalog")
        value = json.loads(result.stdout.decode("utf-8-sig"))
        if not isinstance(value, dict) or not isinstance(value.get("models"), list) or not value["models"]:
            raise ValueError("invalid catalog")
        value = deepcopy(value)
        for model in value["models"]:
            if not isinstance(model, dict):
                raise ValueError("invalid model")
            model.update(shell_type="disabled", apply_patch_tool_type=None, experimental_supported_tools=[],
                         supports_search_tool=False, include_skills_usage_instructions=False,
                         include_plugin_usage_instructions=False, include_apps_usage_instructions=False)
            if policy is not None:
                model["base_instructions"] = policy
        path = Path(directory) / "models.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
        raise IsolationError("Codex 不支持受限模型配置；未提交材料，请检查或升级 Codex") from error


def options(catalog_path, policy=None):
    overrides = ["features.skip_host_skill_discovery=true", 'web_search="disabled"',
                 "project_doc_max_bytes=0", "skills.bundled.enabled=false", "skills.include_instructions=false",
                 "mcp_servers={}", "plugins={}", "include_apps_instructions=false", "tools.update_plan.enabled=false",
                 'approval_policy="never"', 'sandbox_mode="read-only"',
                 "model_catalog_json=" + json.dumps(str(catalog_path))]
    if policy is not None:
        overrides.append("developer_instructions=" + json.dumps(policy, ensure_ascii=False))
    result = []
    for feature in DISABLED:
        result += ["-c", f"features.{feature}=false"]
    for override in overrides:
        result += ["-c", override]
    return result


def exec_command(executable, argv, directory, schema, output, *, policy, model=None, images=(), reasoning=None):
    # Missing isolation switches must be rejected before an evidence-bearing exec.
    try:
        help_result = subprocess.run(argv(executable, "exec", "--help"), capture_output=True, timeout=30,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        help_text = help_result.stdout.decode("utf-8-sig")
        if help_result.returncode or any(flag not in help_text for flag in ("--ignore-user-config", "--ignore-rules", "--output-schema")):
            raise ValueError("unsupported isolation switches")
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise IsolationError("Codex 不支持生成隔离；未提交材料，请升级 Codex") from error
    path = catalog(executable, directory, argv, policy)
    command = argv(executable, "--no-daemon", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                   "--json", "--color", "never", "--skip-git-repo-check", "--sandbox", "read-only",
                   "--output-schema", str(schema), "--output-last-message", str(output))
    command += options(path, policy)
    if reasoning is not None:
        command += ["-c", "model_reasoning_effort=" + json.dumps(reasoning)]
    if model:
        command += ["--model", model]
    for image in images:
        command += ["--image", str(image)]
    return command + ["-"]


def mcp_overrides(config):
    """TOML tables merge; disable inherited MCP entries before any thread."""
    if not isinstance(config, dict) or not isinstance(config.get("mcp_servers", {}), dict):
        raise IsolationError("无法确认 MCP 隔离；未发起生成")
    servers = config.get("mcp_servers", {})
    if any(not isinstance(value, dict) for value in servers.values()):
        raise IsolationError("无法确认 MCP 隔离；未发起生成")
    if not any(value.get("enabled", True) is not False for value in servers.values()):
        return []
    result = []
    for name in servers:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise IsolationError("当前 MCP 名称不能安全隔离；未发起生成")
        result += ["-c", "mcp_servers." + name + ".enabled=false"]
    return result


def verify_config(config):
    if not isinstance(config, dict) or not isinstance(config.get("features"), dict):
        raise IsolationError("无法确认 Codex 能力隔离；未发起生成")
    if mcp_overrides(config) or any(config["features"].get(name) is not False for name in DISABLED):
        raise IsolationError("当前 Codex 无法确认应用只读边界；未发起生成")


def is_tool_event(event):
    if not isinstance(event, dict):
        return True
    item = event.get("item", {})
    return not isinstance(item, dict) or item.get("type") in TOOL_EVENTS
