"""Refresh the explicit portable engineering snapshot; never copy characters."""
from pathlib import Path
import hashlib
import json
import subprocess


PACKAGE = Path(__file__).resolve().parents[1]


def prepare(source: Path):
    output = PACKAGE / "src/ai_workbench/e_chatter/resources/generator"
    receipts = []
    for directory, pattern in (("scripts", "*.py"), ("templates", "*.md"), ("schemas", "*.json")):
        for file in sorted((source / "engineering/generation/character-generator" / directory).glob(pattern)):
            if file.is_symlink():
                raise ValueError("Linked engineering source is not permitted")
            data = file.read_bytes()
            target = output / directory / file.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            receipts.append({"source": file.relative_to(source).as_posix(), "target": target.relative_to(PACKAGE).as_posix(), "sha256": hashlib.sha256(data).hexdigest()})
    for role, folder in (("generator", "generation/character-generator"), ("maintainer", "maintenance/character-maintainer"), ("doctor", "diagnosis/style-doctor")):
        file = source / "engineering" / folder / "SKILL.md"
        receipts.append({"source": file.relative_to(source).as_posix(), "adaptation": f"resources/skills/{role}/SKILL.md", "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    receipt = {"schema": 1, "source_package": "character-system", "source_revision": revision,
               "policy": "Read-only snapshot; ai-workbench owns its adapters. No runtime characters, private configs, corpus or reports are copied.", "files": receipts}
    target = output.parent / "engineering-source.json"
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return len(receipts)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    print(f"Prepared {prepare(args.source.resolve())} engineering resource receipts")
