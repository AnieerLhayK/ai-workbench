from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Dict, List


SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx"}
SOURCE_PLAN_MARKER = "<!-- character-generator-source-plan:start -->"
WORKLIST_PATH_PATTERN = re.compile(r'@"([^"]+)"')
SPEAKER_PREFIX_PATTERN = re.compile(r"^([A-Za-z0-9_\-\u4e00-\u9fff]{1,12})\s*[:：]\s*(.*)$")


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return (
        xml.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .strip()
    )


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _resolve_source_path(source: Dict, project_root: Path, allow_absolute: bool) -> Path:
    raw = str(source["path"])
    path = Path(raw)
    if path.is_absolute():
        if not (allow_absolute or source.get("explicit") is True):
            raise ValueError(
                "Absolute corpus paths must be explicitly supplied through local/private intake or config."
            )
        return path.resolve()
    return (project_root / path).resolve()


def _display_path(path: Path, project_root: Path, local_only: bool = False) -> str:
    if local_only:
        return str(path)
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        parts = path.parts[-3:] if len(path.parts) >= 3 else path.parts
        return "[external]/" + "/".join(parts)


def _is_context_note(line: str) -> bool:
    stripped = line.strip()
    return (
        (stripped.startswith("[") and stripped.endswith("]"))
        or (stripped.startswith("【") and stripped.endswith("】"))
    )


def _contains_speaker_marker(lines: List[str], speaker: str) -> bool:
    for line in lines:
        match = SPEAKER_PREFIX_PATTERN.match(line.strip())
        if match and match.group(1) == speaker:
            return True
    return False


def _filter_source_text(text: str, source: Dict) -> str:
    lines = text.splitlines()
    source_type = str(source.get("source_type", "")).lower()
    exclude_context_notes = source.get("exclude_context_notes", source_type == "chat")
    start_after_time_marker = source.get("start_after_time_marker", source_type == "chat")
    exclude_non_author_speakers = source.get("exclude_non_author_speakers", source_type == "chat")

    if start_after_time_marker:
        body_start = 0
        for index, line in enumerate(lines):
            if line.strip().startswith("【时间"):
                body_start = index + 1
                break
        lines = lines[body_start:]

    if exclude_context_notes:
        lines = [line for line in lines if not _is_context_note(line)]

    author = source.get("author_speaker") or source.get("speaker")
    if exclude_non_author_speakers:
        if not author and _contains_speaker_marker(lines, "A"):
            author = "A"
        kept: List[str] = []
        current_speaker = author
        for line in lines:
            stripped = line.strip()
            match = SPEAKER_PREFIX_PATTERN.match(stripped)
            if match:
                current_speaker = match.group(1)
                if current_speaker == author:
                    content = match.group(2).strip()
                    if content:
                        kept.append(content)
                continue
            if not author or current_speaker == author:
                kept.append(line)
        lines = kept
    return clean_text("\n".join(lines))


def _is_source_plan_readme(path: Path) -> bool:
    if path.name.lower() != "readme.md":
        return False
    try:
        return SOURCE_PLAN_MARKER in path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False


def _should_skip_corpus_file(path: Path, source: Dict) -> bool:
    lower_name = path.name.lower()
    if lower_name == "readme.md" and not source.get("include_readme_as_corpus", False):
        return True
    if lower_name == "worklist.md" and source.get("expand_worklist", True):
        return True
    return _is_source_plan_readme(path)


def _worklist_targets(corpus_path: Path, source: Dict) -> List[Path]:
    if not source.get("expand_worklist", True):
        return []
    worklist = corpus_path / "worklist.md"
    if not worklist.is_file():
        return []

    targets: List[Path] = []
    for raw in WORKLIST_PATH_PATTERN.findall(_read_text(worklist)):
        target = Path(raw)
        if not target.is_absolute():
            target = (corpus_path / target).resolve()
        if target.is_file() and target.suffix.lower() in SUPPORTED_EXTENSIONS:
            targets.append(target)
    return targets


def _iter_corpus_files(corpus_path: Path, source: Dict) -> List[Path]:
    files: List[Path] = []
    seen: set[Path] = set()

    for path in sorted(corpus_path.rglob("*")):
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if _should_skip_corpus_file(path, source):
            continue
        resolved = path.resolve()
        if resolved not in seen:
            files.append(path)
            seen.add(resolved)

    for path in _worklist_targets(corpus_path, source):
        resolved = path.resolve()
        if resolved not in seen:
            files.append(path)
            seen.add(resolved)

    return files


def _iter_sources(config: Dict) -> List[Dict]:
    if config.get("corpus_sources"):
        return [source for source in config["corpus_sources"] if source.get("include", True)]
    return [
        {
            "source_id": "legacy_corpus",
            "path": config["corpus_path"],
            "source_type": "unknown",
            "role": "primary_style_evidence",
            "include": True,
        }
    ]


def _ingest_source(config: Dict, project_root: Path, source: Dict) -> List[Dict]:
    allow_absolute = bool(config.get("allow_absolute_corpus_paths"))
    corpus_path = _resolve_source_path(source, project_root, allow_absolute)
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"Corpus path does not exist: {corpus_path}. "
            "Create the directory and add authorized .txt, .md, or .docx files."
        )
    if not corpus_path.is_dir():
        raise NotADirectoryError(f"Corpus path must be a directory: {corpus_path}")

    documents: List[Dict] = []
    for path in _iter_corpus_files(corpus_path, source):
        text = _read_docx(path) if path.suffix.lower() == ".docx" else _read_text(path)
        text = _filter_source_text(text, source)
        if not text:
            continue

        documents.append(
            {
                "path": _display_path(path, project_root, bool(config.get("local_only_reports"))),
                "text": text,
                "chars": len(text),
                "source_id": source.get("source_id", corpus_path.name),
                "source_type": source.get("source_type", "unknown"),
                "source_role": source.get("role", "primary_style_evidence"),
            }
        )
    return documents


def ingest_corpus(config: Dict, project_root: Path) -> List[Dict]:
    documents: List[Dict] = []
    for source in _iter_sources(config):
        documents.extend(_ingest_source(config, project_root, source))

    if not documents:
        raise ValueError("No readable corpus files found in configured corpus sources.")
    return documents


if __name__ == "__main__":
    raise SystemExit("Use build_character.py as the public entry point.")
