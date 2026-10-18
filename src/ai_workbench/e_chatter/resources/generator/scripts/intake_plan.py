from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple


DEFAULT_FORBIDDEN_TASKS = [
    "impersonation",
    "private_fact_inference",
    "verbatim_reconstruction",
]
DEFAULT_TARGET_TASKS = ["rewrite", "continuation", "critique", "style_transfer", "discussion"]
DEFAULT_PRIVACY_BOUNDARY = (
    "style-inspired output only; no impersonation, private fact inference, "
    "or verbatim reconstruction"
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _as_list(value) -> List:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_target_tasks(values: List) -> List[str]:
    tasks: List[str] = []
    for value in values:
        raw = str(value).strip()
        lowered = raw.lower()
        if raw in {"rewrite", "continuation", "imitation", "critique", "style_transfer", "discussion"}:
            tasks.append(raw)
        elif any(term in lowered for term in ["chat", "friend", "discussion", "conversation", "dialogue", "聊天", "朋友聊天", "讨论"]):
            tasks.append("discussion")
        elif any(term in lowered for term in ["rewrite", "polish", "改写", "润色"]):
            tasks.append("rewrite")
        elif any(term in lowered for term in ["critique", "review", "批评", "评价"]):
            tasks.append("critique")
        elif any(term in lowered for term in ["style transfer", "style_transfer", "风格迁移", "迁移"]):
            tasks.append("style_transfer")
        elif any(term in lowered for term in ["continue", "续写"]):
            tasks.append("continuation")
    deduped: List[str] = []
    for task in tasks:
        if task not in deduped:
            deduped.append(task)
    return deduped or DEFAULT_TARGET_TASKS


def validate_intake(intake: Dict) -> Tuple[List[str], List[str]]:
    missing_required: List[str] = []
    missing_optional: List[str] = []

    if not intake.get("character_id") and not intake.get("display_name"):
        missing_required.append("character_id or display_name")
    if not intake.get("display_name") and not intake.get("character_id"):
        missing_required.append("display_name or character_id")
    if not _as_list(intake.get("corpus_sources")) and not intake.get("corpus_path"):
        missing_required.append("at least one authorized corpus source path")
    if intake.get("authorization_confirmed") is not True:
        missing_required.append("authorization_confirmed=true")
    if not _as_list(intake.get("target_tasks")) and not intake.get("target_interaction_type"):
        missing_required.append("target_tasks or target_interaction_type")
    if intake.get("privacy_boundary_accepted") is not True:
        missing_required.append("privacy_boundary_accepted=true")

    optional_fields = [
        ("personal_profile", "personal profile / background orientation"),
        ("relationship_posture", "desired relationship posture"),
        ("source_normalization", "source normalization preferences"),
    ]
    for field, label in optional_fields:
        if not intake.get(field):
            missing_optional.append(label)

    sources = _as_list(intake.get("corpus_sources"))
    if sources:
        for index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                missing_required.append(f"corpus_sources[{index}] must be an object")
                continue
            if not source.get("path"):
                missing_required.append(f"corpus_sources[{index}].path")
            if not source.get("role"):
                missing_optional.append(f"corpus_sources[{index}].role")
            if "generate_readme" not in source:
                missing_optional.append(f"corpus_sources[{index}].generate_readme preference")

    return missing_required, missing_optional


def render_missing_info_report(missing_required: List[str], missing_optional: List[str]) -> str:
    lines = ["# Character Generator Intake Report", ""]
    if missing_required:
        lines.extend(
            [
                "## Missing Required Information",
                "",
                "Generation stopped. Provide these fields before creating a character:",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in missing_required)
        lines.append("")
    if missing_optional:
        lines.extend(
            [
                "## Missing Optional Information",
                "",
                "Safe defaults can be used after required fields are complete, but quality may improve if these are supplied:",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in missing_optional)
        lines.append("")
    if not missing_required and not missing_optional:
        lines.extend(["## Status", "", "- Intake is complete."])
    return "\n".join(lines).rstrip() + "\n"


def _source_from_path(path: str) -> Dict:
    return {
        "path": path,
        "source_type": "unknown",
        "role": "primary_style_evidence",
        "include": True,
        "generate_readme": False,
        "explicit": True,
    }


def normalize_intake_to_config(intake: Dict) -> Tuple[Dict, List[str]]:
    missing_required, missing_optional = validate_intake(intake)
    if missing_required:
        raise ValueError(render_missing_info_report(missing_required, missing_optional))

    character_id = intake.get("character_id") or _slug(str(intake.get("display_name", "")))
    display_name = intake.get("display_name") or character_id
    target_tasks = _normalize_target_tasks(
        _as_list(intake.get("target_tasks")) or _as_list(intake.get("target_interaction_type"))
    )

    raw_sources = _as_list(intake.get("corpus_sources"))
    if not raw_sources and intake.get("corpus_path"):
        raw_sources = [_source_from_path(str(intake["corpus_path"]))]

    corpus_sources: List[Dict] = []
    for index, source in enumerate(raw_sources, start=1):
        source = dict(source)
        source.setdefault("source_id", f"source_{index:02d}")
        source.setdefault("source_type", "unknown")
        source.setdefault("role", "primary_style_evidence")
        source.setdefault("include", True)
        source.setdefault("generate_readme", False)
        source.setdefault("readme_path", "README.md")
        source.setdefault("explicit", True)
        corpus_sources.append(source)

    config = {
        "character_id": character_id,
        "display_name": display_name,
        "corpus_sources": corpus_sources,
        "output_path": intake.get("output_path") or f"characters/{character_id}",
        "language": intake.get("language") or "zh-CN",
        "privacy_level": intake.get("privacy_level") or "high",
        "style_strength": intake.get("style_strength") or "medium",
        "target_tasks": target_tasks,
        "forbidden_tasks": intake.get("forbidden_tasks") or DEFAULT_FORBIDDEN_TASKS,
        "quote_policy": intake.get("quote_policy") or "short_only",
        "max_quote_chars": intake.get("max_quote_chars", 80),
        "generate_reports": intake.get("generate_reports", True),
        "source_planning_enabled": intake.get("source_planning_enabled", True),
        "generate_corpus_handoff": intake.get("generate_corpus_handoff", True),
        "allow_absolute_corpus_paths": True,
        "privacy_boundary": intake.get("privacy_boundary") or DEFAULT_PRIVACY_BOUNDARY,
        "optional_missing_info": missing_optional,
        "personal_profile": intake.get("personal_profile", ""),
        "relationship_posture": intake.get("relationship_posture", ""),
        "source_normalization": intake.get("source_normalization", ""),
    }
    return config, missing_optional


def write_private_plan(config: Dict, output_path: Path) -> Path:
    import json

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
