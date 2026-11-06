"""Process-local tool guard for a single private CI clone, not a host authority grant."""
import json
from pathlib import Path
import shlex
import sys


def decision(tool, arguments, policy):
    root = Path(policy["workspace"]).resolve()
    skills = [Path(path).resolve() for path in policy.get("skill_roots", [policy["skill"]])]
    name = tool.lower()

    def inside(value, base=root):
        path = Path(value)
        return (path if path.is_absolute() else root / path).resolve().is_relative_to(base)

    if arguments.get("sandbox_permissions") or arguments.get("dangerouslyDisableSandbox"):
        return "CI 修复不允许扩大沙箱权限"
    if name in ("skill",):
        selected = arguments.get("name", arguments.get("skill", ""))
        return None if selected == "gh-fix-ci" else "本任务只加载 gh-fix-ci"
    if name in ("read", "glob", "grep"):
        target = arguments.get("file_path") or arguments.get("path")
        return None if not target or inside(target) or any(inside(target, skill) for skill in skills) else "读取路径超出本次克隆"
    if name in ("edit", "write"):
        target = arguments.get("file_path") or arguments.get("path")
        if not target or not inside(target):
            return "写入路径超出本次克隆"
        parts = (Path(target) if Path(target).is_absolute() else root / target).resolve().relative_to(root).parts
        if any(part.lower() in (".git", ".agents", ".claude", ".dsh") for part in parts) or parts[-1].lower() in ("agents.md", "claude.md"):
            return "CI 控制指令和 Git 元数据只读"
        return None
    if name in ("todo_write", "todowrite", "job_output", "job_list", "job_kill"):
        return None
    if name not in ("pwsh", "bash", "powershell"):
        return "工具未授权用于本次修复"
    workdir = arguments.get("workdir") or arguments.get("cwd")
    if workdir and not inside(workdir):
        return "命令工作目录超出本次克隆"
    command = arguments.get("command", "")
    if command.startswith("& "):
        command = command[2:]
    if any(value in command for value in ("\n", "\r", ";", "&", "||", "|", ">", "<", "`", "$")):
        return "请使用单条命令，不允许命令链或重定向"
    try:
        words = shlex.split(command)
    except ValueError:
        return "命令格式无效"
    if not words:
        return "命令为空"
    executable = Path(words[0].replace("\\", "/")).stem.lower()
    if executable == "git":
        denied = ("--output", "--ext-diff", "--textconv", "--no-index", "--git-dir", "--work-tree", "-c")
        return None if len(words) > 1 and words[1] in ("status", "diff", "show", "rev-parse", "ls-files") and not any(word.startswith(denied) for word in words[2:]) else "仅允许只读 Git 命令"
    if executable == "gh":
        if any(word.startswith(("-t", "-w", "--show-token", "--web", "--hostname")) for word in words):
            return "不允许读取凭据或打开额外入口"
        for word in words:
            if word.startswith(("--repo=", "-R=")) and word.split("=", 1)[1] != policy["repository"]:
                return "GitHub 查询必须属于当前仓库"
            if word.startswith("-R") and len(word) > 2 and word[2:].lstrip("=") != policy["repository"]:
                return "GitHub 查询必须属于当前仓库"
        if "--repo" in words or "-R" in words:
            flag = "--repo" if "--repo" in words else "-R"
            index = words.index(flag)
            if index + 1 >= len(words) or words[index + 1] != policy["repository"]:
                return "GitHub 查询必须属于当前仓库"
        if words[1:3] == ["repo", "view"]:
            rest = words[3:]
            i = 0
            while i < len(rest):
                if rest[i] in ("--json", "--repo", "-R"):
                    i += 2
                    continue
                if not rest[i].startswith("-") and rest[i] != policy["repository"]:
                    return "GitHub 查询必须属于当前仓库"
                i += 1
        return None if words[1:3] in (["auth", "status"], ["pr", "view"], ["pr", "checks"], ["run", "view"], ["repo", "view"]) or words[1:] == ["--version"] else "仅允许读取 PR、检查和日志"
    expected = policy.get("test_command", [])
    if words == expected or words[0:2] == ["python", "-B"] and ["python", *words[2:]] == expected:
        return None
    if executable in ("python", "python3") and len(words) > 1:
        args = [word for word in words[1:] if word != "-B"]
        if args and args[0].replace("\\", "/").endswith("/scripts/inspect_pr_checks.py") and any(inside(args[0], skill) for skill in skills):
            if "--repo" in args:
                index = args.index("--repo")
                if index + 1 >= len(args) or not inside(args[index + 1]):
                    return "检查脚本必须读取当前克隆"
            return None
    return "仅允许配置的测试命令和只读诊断命令"


def main():
    policy = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    data = json.load(sys.stdin)
    reason = decision(data.get("tool_name", data.get("name", "")), data.get("tool_input", data.get("arguments", {})) or {}, policy)
    if "--dsh" in sys.argv:
        print(json.dumps({"allowed": reason is None, "reason": reason}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny" if reason else "allow", "permissionDecisionReason": reason or "已批准的隔离 CI 修复"}}))


if __name__ == "__main__":
    main()
