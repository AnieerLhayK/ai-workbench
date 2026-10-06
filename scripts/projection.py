"""Export/check an explicit portable payload; never contact providers or a remote."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ["PROJECTION_SOURCE.json"]


def provenance(revision=None):
    return {"package": "ai-workbench", "source_path": "packages/ai-workbench", "workspace_commit": revision}


def validate_provenance(value, expected_revision=None, *, require_revision=False):
    if not isinstance(value, dict) or set(value) != set(provenance()):
        raise ValueError("Invalid projection source fields")
    revision = value["workspace_commit"]
    if value != provenance(revision):
        raise ValueError("Invalid projection source identity")
    if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)):
        raise ValueError("Invalid Workspace commit")
    if require_revision and revision is None:
        raise ValueError("Public projection requires a Workspace commit")
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("Projection source revision mismatch")
    return value


def contract_files(contract) -> list[str]:
    files = contract["files"]
    if contract.get("generated_files") != GENERATED:
        raise ValueError("Invalid generated file contract")
    if not isinstance(files, list) or not files or not all(isinstance(name, str) for name in files) or len(files) != len(set(files)):
        raise ValueError("Contract must contain unique files")
    for name in files:
        path = PurePosixPath(name)
        if not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts or name != path.as_posix() or ".git" in path.parts or name in GENERATED:
            raise ValueError(f"Unsafe contract path: {name}")
    return files


def allowed_files(root: Path) -> list[str]:
    files = contract_files(json.loads((root / "projection-contract.json").read_text(encoding="utf-8")))
    for name in files:
        candidate = root / name
        if not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Path escapes package: {name}")
        if any(part.is_symlink() or part.is_junction() for part in (candidate, *candidate.parents)):
            raise ValueError(f"Linked contract path: {name}")
        if not candidate.is_file():
            raise ValueError(f"Missing contract file: {name}")
    return files


def payload_files(root: Path) -> set[str]:
    """Inspect payload only. Root Git metadata is neither exported nor traversed."""
    actual = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs) + files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"Linked preview path: {relative}")
            if relative == ".git":
                if name in dirs:
                    dirs.remove(name)
                continue
            if name in files:
                actual.add(relative)
    return actual


def check(root: Path, expected_revision=None, *, require_revision=False, expected_files=None) -> list[str]:
    files = allowed_files(root) + GENERATED
    if expected_files is not None and set(files) != set(expected_files):
        raise ValueError("Projection contract differs from authoritative contract")
    actual = payload_files(root)
    if actual != set(files):
        raise ValueError(f"Unexpected or missing preview files: {sorted(actual ^ set(files))}")
    validate_provenance(json.loads((root / GENERATED[0]).read_text(encoding="utf-8")), expected_revision, require_revision=require_revision)
    for name in files:
        if name.endswith(".ico"):
            if not (root / name).read_bytes().startswith(b"\x00\x00\x01\x00"):
                raise ValueError(f"Invalid icon in {name}")
            continue
        text = (root / name).read_text(encoding="utf-8")
        if re.search(r"\b[A-Za-z]:[\\/]", text):
            raise ValueError(f"Machine path in {name}")
        if re.search(r"PROJECT_CONTEXT[/\\]|workspace_manifest\.yaml", text):
            raise ValueError(f"Private workspace dependency in {name}")
        if name.endswith(".md"):
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                target = link.split("#")[0]
                if not target or "://" in target:
                    continue
                referenced = (root / name).parent / target
                if not referenced.resolve().is_relative_to(root.resolve()) or not referenced.exists():
                    raise ValueError(f"Broken or private link in {name}: {target}")
    return files


def export(source: Path, destination: Path, *, refresh=False, source_revision=None, git_staging=False) -> list[str]:
    source = source.resolve()
    destination = destination.absolute()
    if destination.resolve().is_relative_to(source):
        raise ValueError("Preview must be outside package source")
    if any(part.is_symlink() or part.is_junction() for part in (destination, *destination.parents)):
        raise ValueError("Preview destination must not use links or junctions")
    files = allowed_files(source)
    marker = provenance(source_revision)
    if source_revision is None and (source / GENERATED[0]).is_file():
        marker = json.loads((source / GENERATED[0]).read_text(encoding="utf-8"))
    validate_provenance(marker)
    if destination.exists() and any(destination.iterdir()):
        if git_staging and set(path.name for path in destination.iterdir()) == {".git"}:
            payload_files(destination)  # reject linked metadata without traversing it
        elif refresh:
            check(destination, expected_files=files + GENERATED)
        else:
            raise ValueError("Use an empty destination or explicitly refresh a verified preview")
    destination.mkdir(parents=True, exist_ok=True)
    for name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    (destination / GENERATED[0]).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    return check(destination, source_revision, expected_files=files + GENERATED)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export", "check"))
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--source-revision", help="Reviewed Workspace commit; omitted for local preview")
    parser.add_argument("--require-revision", action="store_true", help="Check public provenance")
    args = parser.parse_args()
    if args.refresh and args.mode != "export":
        parser.error("--refresh is only valid for export")
    if args.require_revision and args.mode != "check":
        parser.error("--require-revision is only valid for check")
    files = export(ROOT, args.destination, refresh=args.refresh, source_revision=args.source_revision) if args.mode == "export" else check(args.destination, args.source_revision, require_revision=args.require_revision)
    print(f"{args.mode}: {len(files)} portable files verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
