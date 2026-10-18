"""The application owns copies. No operation in this module edits an input."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import uuid

import yaml


class ChatterError(ValueError):
    pass


def uid() -> str:
    return uuid.uuid4().hex


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def io_path(path: Path) -> Path:
    """Support long task-copy paths without changing Windows system policy."""
    value = str(path.absolute())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


def plain_path(path: Path) -> Path:
    path = path.absolute()
    for part in (*reversed(path.parents), path):
        probe = io_path(part)
        if probe.exists() or probe.is_symlink():
            info = probe.lstat()
            if probe.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ChatterError("不能通过链接或重解析目录读取、保存角色；请选择实际目录")
    return path


def relative(name: str) -> str:
    parts = name.replace("\\", "/").split("/")
    if (not name or PureWindowsPath(name).drive or name.startswith(("/", "\\"))
            or any(x in ("", ".", "..") or ":" in x or x.endswith((" ", ".")) for x in parts)
            or any(re.match(r"(?i)^(con|prn|aux|nul|com\d|lpt\d)(?:\.|$)", x) for x in parts)):
        raise ChatterError("文件名必须是副本内的相对路径")
    return "/".join(parts)


def inside(root: Path, name: str) -> Path:
    path = plain_path(root / relative(name))
    if not path.resolve().is_relative_to(root.resolve()):
        raise ChatterError("文件超出应用副本范围")
    return path


def atomic(path: Path, content: bytes) -> None:
    plain_path(path)
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + uid()[:12] + ".tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def tree(root: Path) -> dict[str, bytes]:
    """Read only one selected package; prune payloads and never follow links."""
    root = io_path(plain_path(root))
    if not root.is_dir():
        raise ChatterError("角色目录不存在")
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "corpus", "raw_material"}]
        for name in [*dirs, *files]:
            plain_path(Path(directory, name))
        for name in files:
            path = Path(directory, name)
            if path.suffix in {".pyc", ".db", ".sqlite", ".log"}:
                continue
            if len(result) >= 4096 or sum(map(len, result.values())) + path.stat().st_size > 128 * 1024 * 1024:
                raise ChatterError("角色包超过 4096 文件或 128 MB，请移除无关资料")
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def fingerprint(files: dict[str, bytes]) -> str:
    return digest(json.dumps({k: digest(v) for k, v in sorted(files.items())}, sort_keys=True).encode())


def write_tree(root: Path, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        atomic(inside(root, name), content)


def skill_info(files: dict[str, bytes]) -> dict:
    try:
        content = files["SKILL.md"].decode("utf-8-sig")
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.+)", content, re.S)
        if not match:
            raise ValueError()
        metadata = yaml.safe_load(match[1])
        if not isinstance(metadata, dict) or any(not isinstance(metadata.get(k), str) or not metadata[k].strip() for k in ("name", "description")):
            raise ValueError()
        # Actual Markdown resource links and conventional reference-file routes.
        links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", content)
        links += re.findall(r"`((?:references|prompts)/[^`\n]+\.(?:md|txt|json))`", content)
        for link in links:
            link = link.split("#", 1)[0]
            if not link or "://" in link:
                continue
            if relative(link.removeprefix("./")) not in files:
                raise ChatterError(f"角色引用文件缺失：{link}")
        return {"name": metadata["name"].strip(), "description": metadata["description"].strip()}
    except ChatterError:
        raise
    except (KeyError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise ChatterError("需要有效的 SKILL.md：name、description 和非空角色指令") from error


def texts(files: dict[str, bytes]) -> dict[str, str]:
    return {k: v.decode("utf-8-sig", errors="replace") for k, v in files.items()
            if Path(k).suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml", ".toml"}}
