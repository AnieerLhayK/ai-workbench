"""External preferences; portable source contains no private host paths."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re
import posixpath
from uuid import uuid4

from ..storage import atomic_json
from .library import DiaryError, load_json, digest, is_link, now

TOPICS = [
    {"id": "awards", "name": "评奖评优", "description": "整理资格、成果与贡献证据；不虚构荣誉或贡献。", "prompt": "区分已获成果、参与贡献及待核实材料。"},
    {"id": "party", "name": "入党事务", "description": "整理实际经历、学习与事务材料；不代编政治经历。", "prompt": "以实际记录为依据，标注需要本人核实的时间和事项。"},
    {"id": "meeting", "name": "组会汇报", "description": "组织研究进展、问题和后续安排；区分完成、尝试与计划。", "prompt": "围绕本阶段进展、证据、问题与下一步组织材料。"},
    {"id": "course", "name": "课程结项", "description": "对照课程要求整理成果、过程与未完成事项。", "prompt": "说明完成内容、提交物、个人贡献及尚未完成的要求。"},
]


class Settings:
    def __init__(self, root=None, config=None):
        self.path = Path(root) / "settings.json" if root else None
        self.config = deepcopy(config or {})
        anchor = datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)
        defaults = {"theme": "light", "cycles": {
            kind: {"enabled": True, "days": days, "anchor": anchor.isoformat(), "last_end": None}
            for kind, days in (("development", 7), ("work", 7), ("personal", 21))},
            "sources": [{"id": f"root-{i}", "path": value, "enabled": True, "type": "projects" if i else "git"}
                        for i, value in enumerate(self.config.get("source_roots", []))],
            "topics": deepcopy(TOPICS), "imports": [], "reports": [], "own_threads": []}
        self.data = load_json(self.path, defaults) if self.path else defaults
        if not isinstance(self.data, dict) or not isinstance(self.data.get("cycles"), dict):
            raise DiaryError("设置格式损坏；原文件已保留")
        for key, value in defaults.items():
            self.data.setdefault(key, value)

    def update(self, **values):
        updated = load_json(self.path, self.data) if self.path else deepcopy(self.data)
        if not isinstance(updated, dict):
            raise DiaryError("设置格式损坏，未覆盖原文件")
        updated.update(deepcopy(values))
        if self.path:
            atomic_json(self.path, updated)
        self.data = updated


class StyleResources:
    """Manual, immutable private snapshots; current.json is the only commit point."""
    def __init__(self, config):
        self.config = config
        root = config.get("data_root")
        self.root = Path(root) / "user-style" if root else None

    def status(self):
        if self.config.get("demo"):
            return {"available": False, "message": "演示模式不读取 user-style 私有镜像"}
        if not self.root:
            return {"available": False, "message": "尚未配置私人数据目录"}
        try:
            current = load_json(self.root / "current.json", {})
            if not current:
                return {"available": False, "message": "尚未同步，请点击同步 user-style"}
            self._read(current)
            return {**current, "available": True, "message": "私有镜像可用"}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            return {"available": False, "message": f"user-style 镜像损坏：{error}"}

    def _read(self, current):
        version = current["version"]
        if not re.fullmatch(r"[0-9a-f]{32}", version):
            raise DiaryError("无效的 user-style 快照")
        folder = self.root / version
        texts = {}
        if not isinstance(current.get("files"), dict) or len(current["files"]) > 100:
            raise DiaryError("无效的 user-style 文件清单")
        total = 0
        for name, expected in current["files"].items():
            path = Path(name)
            if path.drive or path.root or ".." in path.parts:
                raise DiaryError("无效的 user-style 资源路径")
            target = folder / path
            if any(is_link(p) for p in [target, *target.parents]):
                raise DiaryError("user-style 镜像不能使用链接")
            if target.stat().st_size > 250_000:
                raise DiaryError("user-style 资源超过读取预算")
            value = target.read_bytes().decode("utf-8")
            total += len(value.encode("utf-8"))
            if total > 2_000_000:
                raise DiaryError("user-style 超过读取预算")
            if digest(value) != expected:
                raise DiaryError("user-style 镜像已修改，请重新同步")
            texts[name] = value
        if "SKILL.md" not in texts:
            raise DiaryError("user-style 镜像缺少 SKILL.md")
        return texts

    def sync(self, source=None):
        if self.config.get("demo") or not self.root:
            raise DiaryError("请在真实配置中同步 user-style")
        source = source or self.config.get("zf_root", "")
        root = Path(source)
        if not source or not root.is_absolute() or not root.is_dir():
            raise DiaryError("user-style 源目录必须是存在的绝对路径")
        # Resolve the configured source once: an existing platform projection may
        # be a junction. The independent private destination never uses links.
        root = root.resolve()
        pending, texts, total = [Path("SKILL.md")], {}, 0
        while pending:
            relative = pending.pop()
            name = relative.as_posix()
            if name in texts:
                continue
            if relative.drive or relative.root or ".." in relative.parts:
                raise DiaryError("user-style 引用超出源目录")
            path = root / relative
            blocked = {"raw", "corpus", "raw-corpus", "private-corpus", "private_corpus", "raw_corpus", "reports", "tests"}
            if any(part.lower() in blocked or Path(part).stem.lower() in blocked for part in relative.parts):
                raise DiaryError("user-style 不同步原始语料或维护资料")
            if any(is_link(p) for p in [path, *list(path.parents)[:len(relative.parts)-1]]):
                raise DiaryError("user-style 引用不能是链接")
            if not path.is_file() or path.stat().st_size > 250_000:
                raise DiaryError(f"user-style 资源缺失或过大：{name}")
            value = path.read_bytes()
            total += len(value)
            if total > 2_000_000 or len(texts) >= 100:
                raise DiaryError("user-style 超过同步预算")
            text = value.decode("utf-8-sig")
            texts[name] = text
            refs = re.findall(r"\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+[\"'][^\n]*?[\"'])?\)", text)
            refs += re.findall(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?", text, re.MULTILINE)
            refs += re.findall(r"`((?:(?:references|prompts)/|\.{1,2}/)[^`\n]+\.(?:md|txt|json|yaml|yml)(?:#[^`\n]*)?)`", text)
            refs += [ref for ref in re.findall(r"`([\w-]+\.(?:md|txt|json|yaml|yml))`", text)
                     if (root / relative.parent / ref).is_file()]
            refs += re.findall(r"(?:references|prompts)/[\w./-]+\.(?:md|txt|json|yaml|yml)", text)
            for ref in refs:
                ref = ref.split("#", 1)[0]
                if not ref or "://" in ref or ref.startswith("mailto:"):
                    continue
                candidate = Path(ref)
                if candidate.drive or candidate.root:
                    raise DiaryError("user-style 引用必须为相对资源")
                joined = ref if candidate.parts[0] in ("references", "prompts") else (relative.parent / candidate).as_posix()
                normalized = Path(posixpath.normpath(joined))
                if ".." in normalized.parts or normalized.parts[0] not in ("references", "prompts"):
                    raise DiaryError("user-style 引用超出允许的资源目录")
                pending.append(normalized)
        # Reject a source that changed while traversing its reference closure.
        for name, value in texts.items():
            if (root / name).read_bytes().decode("utf-8-sig") != value:
                raise DiaryError("user-style 源文件同步期间发生变化，请重试")
        version = uuid4().hex
        target = self.root / version
        if any(is_link(p) for p in [target, *target.parents]):
            raise DiaryError("user-style 私人目录不能使用链接")
        for name, text in texts.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
        current = {"version": version, "source": str(root), "synced_at": now(),
                   "files": {name: digest(text) for name, text in texts.items()}}
        self._read(current)
        atomic_json(self.root / "current.json", current)
        return self.status()

    def load(self):
        if not self.root:
            raise DiaryError("user-style 尚未同步，请在设置中同步")
        current = load_json(self.root / "current.json", {})
        if not current:
            raise DiaryError("user-style 尚未同步，请在设置中同步")
        return self._read(current)


def style_resources(config, use_zf=False):
    """Custom prose is live; user-style changes only through manual sync."""
    prose = config.get("prose_path", "").strip()
    paths = [Path(prose) if prose else Path(__file__).with_name("prose.md")]
    texts, fingerprints = [], {}
    for path in paths:
        if not path.is_file():
            raise DiaryError(f"写作资源缺失，请在设置中修复：{path}")
        value = path.read_text(encoding="utf-8-sig")
        texts.append(f"写作要求（{path.name}）：\n{value}")
        fingerprints[str(path)] = digest(value)
    if use_zf:
        resources = StyleResources(config).load()
        for name, value in resources.items():
            texts.append(f"user-style 资源（{name}）：\n{value}")
            fingerprints["user-style/" + name] = digest(value)
    return "\n\n".join(texts), fingerprints
