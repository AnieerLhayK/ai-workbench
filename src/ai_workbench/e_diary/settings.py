"""External preferences; portable source contains no private host paths."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from ..storage import atomic_json
from .library import DiaryError, load_json

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


def style_resources(config, use_zf=False):
    """Read live resources for each job; fingerprints audit the inputs, not pin them."""
    from .library import digest
    paths = [Path(config.get("prose_path", ""))]
    if use_zf:
        root = Path(config.get("zf_root", ""))
        paths += [root / "SKILL.md", *[root / "references" / name for name in
                  ("style_profile.md", "voice_card.md", "sentence_and_rhythm.md", "anti_patterns.md")]]
    texts, fingerprints = [], {}
    for path in paths:
        if not path.is_file():
            raise DiaryError(f"写作资源缺失，请在设置中修复：{path}")
        value = path.read_text(encoding="utf-8-sig")
        texts.append(f"写作要求（{path.name}）：\n{value}")
        fingerprints[str(path)] = digest(value)
    return "\n\n".join(texts), fingerprints
