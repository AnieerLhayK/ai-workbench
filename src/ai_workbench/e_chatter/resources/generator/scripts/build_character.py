from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from anonymize_corpus import anonymize_documents, write_privacy_report
from chunk_corpus import chunk_documents
from corpus_stats import compute_stats, write_corpus_stats
from extract_style import build_style_values
from ingest_corpus import ingest_corpus
from intake_plan import normalize_intake_to_config, write_private_plan
from validate_pack import validate_pack, write_evaluation_report
from write_manifest import write_manifest

README_START = "<!-- character-generator-source-plan:start -->"
README_END = "<!-- character-generator-source-plan:end -->"


def load_json(path: Path) -> Dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _check_type(field: str, value, expected: str) -> List[str]:
    type_map = {
        "string": str,
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    if expected == "integer" and isinstance(value, bool):
        return [f"`{field}` must be an integer."]
    if expected in type_map and not isinstance(value, type_map[expected]):
        return [f"`{field}` must be {expected}."]
    return []


def _validate_value(field: str, value, rules: Dict) -> List[str]:
    issues: List[str] = []
    issues.extend(_check_type(field, value, rules.get("type")))

    if "enum" in rules and value not in rules["enum"]:
        issues.append(f"`{field}` must be one of {rules['enum']}; got `{value}`.")
    if isinstance(value, str):
        if "minLength" in rules and len(value) < rules["minLength"]:
            issues.append(f"`{field}` must not be empty.")
        if "pattern" in rules and not re.match(rules["pattern"], value):
            issues.append(f"`{field}` contains unsupported characters.")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in rules and value < rules["minimum"]:
            issues.append(f"`{field}` must be >= {rules['minimum']}.")
        if "maximum" in rules and value > rules["maximum"]:
            issues.append(f"`{field}` must be <= {rules['maximum']}.")
    if isinstance(value, list):
        if "minItems" in rules and len(value) < rules["minItems"]:
            issues.append(f"`{field}` must include at least {rules['minItems']} item(s).")
        if rules.get("uniqueItems") and len(value) != len(set(value)):
            issues.append(f"`{field}` must not contain duplicates.")
        item_rules = rules.get("items", {})
        for index, item in enumerate(value):
            item_field = f"{field}[{index}]"
            if item_rules.get("type") == "object":
                if not isinstance(item, dict):
                    issues.append(f"`{item_field}` must be object.")
                    continue
                required = item_rules.get("required", [])
                for required_field in required:
                    if required_field not in item:
                        issues.append(f"Missing required config field: `{item_field}.{required_field}`.")
                allowed = set(item_rules.get("properties", {}).keys())
                for child_field in item:
                    if child_field not in allowed:
                        issues.append(f"Unknown config field: `{item_field}.{child_field}`.")
                for child_field, child_rules in item_rules.get("properties", {}).items():
                    if child_field in item:
                        issues.extend(
                            _validate_value(
                                f"{item_field}.{child_field}",
                                item[child_field],
                                child_rules,
                            )
                        )
                continue
            if item_rules.get("type") and not isinstance(item, str):
                issues.append(f"`{field}` items must be strings.")
            if "enum" in item_rules and item not in item_rules["enum"]:
                issues.append(f"`{field}` contains unsupported item `{item}`.")

    return issues


def validate_config(config: Dict, schema_path: Path | None = None) -> None:
    schema_path = schema_path or PROJECT_ROOT / "schemas" / "character_config.schema.json"
    schema = load_json(schema_path)
    issues: List[str] = []

    for field in schema.get("required", []):
        if field not in config:
            issues.append(f"Missing required config field: `{field}`.")

    if not config.get("corpus_path") and not config.get("corpus_sources"):
        issues.append("Missing required config field: `corpus_path` or `corpus_sources`.")

    allowed = set(schema.get("properties", {}).keys())
    for field in config:
        if field not in allowed:
            issues.append(f"Unknown config field: `{field}`.")

    for field, rules in schema.get("properties", {}).items():
        if field not in config:
            continue
        issues.extend(_validate_value(field, config[field], rules))

    if issues:
        raise ValueError("Config validation failed:\n- " + "\n- ".join(issues))


def render_template(template_name: str, values: Dict) -> str:
    template_path = PROJECT_ROOT / "templates" / template_name
    return template_path.read_text(encoding="utf-8").format(**values)


def _path_for_display(path: Path, project_root: Path, local_only: bool = False) -> str:
    if local_only:
        return str(path)
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        parts = path.parts[-3:] if len(path.parts) >= 3 else path.parts
        return "[external]/" + "/".join(parts)


def _resolve_source_path(source: Dict, project_root: Path) -> Path:
    raw = str(source.get("path", ""))
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _render_source_readme_block(source: Dict, source_path: Path, project_root: Path) -> str:
    readme_name = str(source.get("readme_path", "README.md")).replace("\\", "/").lower()
    files = [
        path
        for path in sorted(source_path.rglob("*"))
        if path.is_file() and not path.name.startswith(".")
        and str(path.relative_to(source_path)).replace("\\", "/").lower() != readme_name
    ][:50]
    inventory = "\n".join(
        f"- `{_path_for_display(path, project_root)}` ({path.suffix.lower() or 'no extension'})"
        for path in files
    ) or "- No readable files were inventoried yet."
    return "\n".join(
        [
            README_START,
            "# Corpus Source Plan",
            "",
            f"- Source role: `{source.get('role', 'primary_style_evidence')}`",
            f"- Source type: `{source.get('source_type', 'unknown')}`",
            f"- Include in style extraction: `{source.get('include', True)}`",
            f"- Speaker: `{source.get('speaker', source.get('author_speaker', 'unspecified'))}`",
            f"- Speaker rules: {source.get('speaker_rules', 'Not supplied.')}",
            f"- Notes: {source.get('notes', 'Not supplied.')}",
            "",
            "## File Inventory",
            "",
            inventory,
            "",
            "## Reading Contract",
            "",
            "- Treat this README as source-planning guidance, not as author voice.",
            "- Keep context notes, other speakers, filenames, and conversion artifacts separate from style evidence.",
            "- Preserve useful oral rhythm or formatting irregularity unless normalization notes say otherwise.",
            "- Do not infer private biography or produce impersonation claims from this source.",
            README_END,
        ]
    ) + "\n"


def write_source_readmes(config: Dict) -> List[Dict]:
    if not config.get("source_planning_enabled"):
        return []
    records: List[Dict] = []
    for source in config.get("corpus_sources", []):
        if not source.get("generate_readme"):
            continue
        source_path = _resolve_source_path(source, PROJECT_ROOT)
        if not source_path.is_dir():
            records.append(
                {
                    "source_id": source.get("source_id", ""),
                    "path": _path_for_display(source_path, PROJECT_ROOT),
                    "status": "missing_source_directory",
                }
            )
            continue
        readme_path = source_path / source.get("readme_path", "README.md")
        block = _render_source_readme_block(source, source_path, PROJECT_ROOT)
        if readme_path.exists():
            existing = readme_path.read_text(encoding="utf-8", errors="replace")
            if README_START in existing and README_END in existing:
                before = existing.split(README_START, 1)[0]
                after = existing.split(README_END, 1)[1]
                text = before.rstrip() + "\n\n" + block + after.lstrip()
            else:
                text = existing.rstrip() + "\n\n" + block
        else:
            text = block
        readme_path.write_text(text, encoding="utf-8")
        records.append(
            {
                "source_id": source.get("source_id", ""),
                "path": _path_for_display(source_path, PROJECT_ROOT),
                "readme_path": _path_for_display(readme_path, PROJECT_ROOT),
                "status": "written",
            }
        )
    return records


def write_corpus_reading_handoff(
    output_path: Path,
    config: Dict,
    readme_records: List[Dict],
    documents: List[Dict],
    chunks: List[Dict],
) -> Path | None:
    if not config.get("generate_corpus_handoff") and not config.get("source_planning_enabled"):
        return None
    lines = [
        "# Corpus Reading Handoff",
        "",
        "This handoff records source-planning decisions for future regeneration and maintainer review. It intentionally omits raw private excerpts.",
        "",
        "## Sources",
        "",
    ]
    for source in config.get("corpus_sources", []):
        source_path = _resolve_source_path(source, PROJECT_ROOT)
        lines.extend(
            [
                f"### {source.get('source_id', source_path.name)}",
                "",
                f"- Path: `{_path_for_display(source_path, PROJECT_ROOT, bool(config.get('local_only_reports')))}`",
                f"- Type: `{source.get('source_type', 'unknown')}`",
                f"- Role: `{source.get('role', 'primary_style_evidence')}`",
                f"- Include: `{source.get('include', True)}`",
                f"- Speaker rules: {source.get('speaker_rules', 'Not supplied.')}",
                f"- Notes: {source.get('notes', 'Not supplied.')}",
                "",
            ]
        )
    lines.extend(["## README Generation", ""])
    if readme_records:
        for record in readme_records:
            lines.append(
                f"- `{record.get('source_id', '')}`: {record.get('status')} at `{record.get('readme_path', record.get('path', ''))}`"
            )
    else:
        lines.append("- No source README files were generated.")
    lines.extend(
        [
            "",
            "## Normalization And Chunking",
            "",
            f"- Documents ingested: `{len(documents)}`",
            f"- Chunks generated: `{len(chunks)}`",
            f"- Source normalization preferences: {config.get('source_normalization') or 'Not supplied.'}",
            "- Speaker/context filtering follows per-source metadata when supplied.",
            "",
            "## Missing Optional Information",
            "",
        ]
    )
    optional_missing = config.get("optional_missing_info", [])
    if optional_missing:
        lines.extend(f"- {item}" for item in optional_missing)
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Maintainer Follow-Up",
            "",
            "- Review whether source roles match the intended interaction tasks.",
            "- Add personal profile or relationship posture notes if runtime outputs feel generic.",
            "- Preserve README source contracts during future regeneration.",
            "",
            "## Privacy Caveats",
            "",
            "- Do not use source paths, filenames, or context notes as private facts in generated runtime output.",
            "- Do not treat chat partners or annotations as author voice unless source metadata explicitly says so.",
        ]
    )
    handoff_path = output_path / "reports" / "corpus_reading_handoff.md"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return handoff_path


def write_generated_files(output_path: Path, config: Dict, values: Dict) -> None:
    for folder in ["references", "prompts", "reports", Path("tests") / "cases"]:
        (output_path / folder).mkdir(parents=True, exist_ok=True)

    root_templates = {
        "SKILL.md": "character_SKILL.template.md",
        "README.md": "character_README.template.md",
    }
    reference_templates = {
        "style_profile.md": "style_profile.template.md",
        "voice_card.md": "voice_card.template.md",
        "writing_patterns.md": "writing_patterns.template.md",
        "imagery_and_themes.md": "imagery_and_themes.template.md",
        "sentence_and_rhythm.md": "sentence_and_rhythm.template.md",
        "vocabulary_bank.md": "vocabulary_bank.template.md",
        "example_fragments.md": "example_fragments.template.md",
        "anti_patterns.md": "anti_patterns.template.md",
        "task_recipes.md": "task_recipes.template.md",
        "evaluation_rubric.md": "evaluation_rubric.template.md",
        "corpus_notes.md": "corpus_notes.template.md",
    }
    prompt_templates = {
        "rewrite_prompt.md": "prompt_rewrite.template.md",
        "continuation_prompt.md": "prompt_continuation.template.md",
        "imitation_prompt.md": "prompt_imitation.template.md",
        "critique_prompt.md": "prompt_critique.template.md",
        "style_transfer_prompt.md": "prompt_style_transfer.template.md",
        "discussion_prompt.md": "prompt_discussion.template.md",
    }
    validation_case_templates = {
        "README.md": "validation_cases_README.template.md",
        "001-rewrite-basic.template.md": "validation_case_rewrite_basic.template.md",
        "002-continuation.template.md": "validation_case_continuation.template.md",
        "003-critique-too-ai.template.md": "validation_case_critique_too_ai.template.md",
        "004-style-strength.template.md": "validation_case_style_strength.template.md",
        "005-privacy-boundary.template.md": "validation_case_privacy_boundary.template.md",
        "006-discussion.template.md": "validation_case_discussion.template.md",
    }

    for filename, template_name in root_templates.items():
        (output_path / filename).write_text(render_template(template_name, values), encoding="utf-8")
    for filename, template_name in reference_templates.items():
        (output_path / "references" / filename).write_text(
            render_template(template_name, values), encoding="utf-8"
        )
    for filename, template_name in prompt_templates.items():
        (output_path / "prompts" / filename).write_text(
            render_template(template_name, values), encoding="utf-8"
        )
    for filename, template_name in validation_case_templates.items():
        (output_path / "tests" / "cases" / filename).write_text(
            render_template(template_name, values), encoding="utf-8"
        )

    build_report = [
        "# Build Report",
        "",
        f"- Character ID: `{config['character_id']}`",
        f"- Display name: `{config['display_name']}`",
        f"- Output path: `{config['output_path']}`",
        f"- Target tasks: {', '.join(config['target_tasks'])}",
        f"- Forbidden tasks: {', '.join(config['forbidden_tasks'])}",
        "",
        "The package was generated as a style-inspired writing skill, not an identity simulator.",
    ]
    (output_path / "reports" / "build_report.md").write_text("\n".join(build_report) + "\n", encoding="utf-8")


def _normalize_legacy_config(config: Dict) -> Dict:
    config = dict(config)
    if config.get("corpus_path") and not config.get("corpus_sources"):
        config["corpus_sources"] = [
            {
                "source_id": "legacy_corpus",
                "path": config["corpus_path"],
                "source_type": "unknown",
                "role": "primary_style_evidence",
                "include": True,
                "generate_readme": False,
                "explicit": False,
            }
        ]
    return config


def _run_build(config: Dict) -> Dict:
    output_path = (PROJECT_ROOT / config["output_path"]).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    readme_records = write_source_readmes(config)
    documents = ingest_corpus(config, PROJECT_ROOT)
    sanitized_docs, privacy_counts = anonymize_documents(documents, config)
    chunks = chunk_documents(sanitized_docs)
    stats = compute_stats(sanitized_docs)
    values = build_style_values(config, stats, chunks, privacy_counts)

    write_generated_files(output_path, config, values)
    write_privacy_report(config, privacy_counts, output_path)
    write_corpus_stats(stats, output_path)
    write_corpus_reading_handoff(output_path, config, readme_records, sanitized_docs, chunks)

    ok, issues = validate_pack(output_path, config)
    write_evaluation_report(output_path, ok, issues)
    write_manifest(output_path, config, privacy_counts)

    if not ok:
        raise RuntimeError(
            f"Generated package failed validation for {config['character_id']}:\n- "
            + "\n- ".join(issues)
        )

    return {
        "character_id": config["character_id"],
        "output_path": str(output_path),
        "files": len([p for p in output_path.rglob("*") if p.is_file()]),
        "chunks": len(chunks),
        "optional_missing": config.get("optional_missing_info", []),
    }


def build_character(config_path: Path) -> Dict:
    config_path = config_path.resolve()
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}. "
            "Please create it first or copy configs/character_config.example.json."
        )
    config = load_json(config_path)
    validate_config(config)
    return _run_build(_normalize_legacy_config(config))


def build_character_from_intake(intake_path: Path, plan_output: Path | None = None) -> Dict:
    intake = load_json(intake_path)
    config, _optional_missing = normalize_intake_to_config(intake)
    validate_config(config)
    if plan_output:
        write_private_plan(config, plan_output)
    return _run_build(config)


def is_batch_skipped_config(path: Path) -> bool:
    if path.name == "character_config.example.json":
        return True
    if path.name.endswith(".draft.json"):
        return True
    if "_drafts" in path.parts:
        return True

    config = load_json(path)
    return config.get("enabled", True) is False


def iter_all_configs() -> List[Path]:
    config_dir = PROJECT_ROOT / "configs"
    return [path for path in sorted(config_dir.rglob("*.json")) if not is_batch_skipped_config(path)]


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build platform-neutral style-inspired character skill packages.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config", help="Path to a character config JSON file.")
    group.add_argument("--intake", help="Path to a conversational intake JSON file.")
    group.add_argument(
        "--all",
        action="store_true",
        help="Build every enabled config in configs/, excluding examples and drafts.",
    )
    parser.add_argument(
        "--write-plan",
        help="Optional path for writing the normalized internal build plan.",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.intake:
            results = [
                build_character_from_intake(
                    Path(args.intake),
                    Path(args.write_plan) if args.write_plan else None,
                )
            ]
        else:
            config_paths = iter_all_configs() if args.all else [Path(args.config)]
            if args.all and not config_paths:
                raise FileNotFoundError("No enabled character configs found under configs/.")

            results = [build_character(path) for path in config_paths]
    except Exception as exc:
        print(f"[character-generator] ERROR: {exc}", file=sys.stderr)
        return 1

    print("[character-generator] Build complete.")
    for result in results:
        print(
            f"- {result['character_id']}: {result['output_path']} "
            f"({result['files']} files, {result['chunks']} chunks)"
        )
        if result.get("optional_missing"):
            print("  Optional missing info:")
            for item in result["optional_missing"]:
                print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
