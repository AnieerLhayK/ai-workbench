from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple


REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "references/style_profile.md",
    "references/voice_card.md",
    "references/writing_patterns.md",
    "references/imagery_and_themes.md",
    "references/sentence_and_rhythm.md",
    "references/vocabulary_bank.md",
    "references/example_fragments.md",
    "references/anti_patterns.md",
    "references/task_recipes.md",
    "references/evaluation_rubric.md",
    "references/corpus_notes.md",
    "prompts/rewrite_prompt.md",
    "prompts/continuation_prompt.md",
    "prompts/imitation_prompt.md",
    "prompts/critique_prompt.md",
    "prompts/style_transfer_prompt.md",
    "prompts/discussion_prompt.md",
    "reports/build_report.md",
    "reports/privacy_report.md",
    "reports/corpus_stats.md",
    "tests/cases/README.md",
    "tests/cases/001-rewrite-basic.template.md",
    "tests/cases/002-continuation.template.md",
    "tests/cases/003-critique-too-ai.template.md",
    "tests/cases/004-style-strength.template.md",
    "tests/cases/005-privacy-boundary.template.md",
    "tests/cases/006-discussion.template.md",
]

SAFETY_TERMS = ["style-inspired", "impersonat", "private", "quote", "drift"]
FRONTMATTER_PATTERN = re.compile(
    r"\A---\r?\nname:\s*[^\r\n]+\r?\ndescription:\s*[^\r\n]+\r?\n---"
)


def _find_long_quotes(text: str, max_quote_chars: int) -> List[str]:
    quoted = re.findall(r"[\"“](.*?)[\"”]", text, flags=re.S)
    quoted.extend(re.findall(r"```(?:.*?)\n(.*?)```", text, flags=re.S))
    return [q.strip() for q in quoted if len(q.strip()) > max_quote_chars]


def validate_pack(output_path: Path, config: Dict) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    for relative in REQUIRED_FILES:
        path = output_path / relative
        if not path.exists():
            issues.append(f"Missing required file: {relative}")
        elif path.is_file() and path.stat().st_size == 0:
            issues.append(f"Required file is empty: {relative}")

    skill_path = output_path / "SKILL.md"
    if skill_path.exists():
        skill_text = skill_path.read_text(encoding="utf-8")
        lowered = skill_text.lower()
        if not FRONTMATTER_PATTERN.search(skill_text):
            issues.append("SKILL.md missing required YAML frontmatter with name and description.")
        for term in SAFETY_TERMS:
            if term not in lowered:
                issues.append(f"SKILL.md missing safety boundary term: {term}")
    else:
        skill_text = ""

    for path in output_path.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for quote in _find_long_quotes(text, int(config["max_quote_chars"])):
            issues.append(
                f"Long quote over {config['max_quote_chars']} chars in "
                f"{path.relative_to(output_path)}: {quote[:40]}..."
            )

    references_path = output_path / "references"
    if references_path.exists():
        for path in references_path.glob("*.md"):
            text = path.read_text(encoding="utf-8").strip()
            if len(text) < 120:
                issues.append(f"Reference appears too thin: {path.name}")
            vague_count = sum(text.count(term) for term in ["细腻", "真挚", "优美"])
            if vague_count > 3:
                issues.append(f"Reference may be too vague: {path.name}")

    return not issues, issues


def render_evaluation_report(ok: bool, issues: List[str]) -> str:
    lines = ["# Evaluation Report", "", f"- Status: {'pass' if ok else 'fail'}", ""]
    if issues:
        lines.extend(["## Issues", ""])
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.extend(["## Issues", "", "- None"])
    return "\n".join(lines) + "\n"


def write_evaluation_report(output_path: Path, ok: bool, issues: List[str]) -> Path:
    report_path = output_path / "reports" / "evaluation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_evaluation_report(ok, issues), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    raise SystemExit("Use build_character.py as the public entry point.")
