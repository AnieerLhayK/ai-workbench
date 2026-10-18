from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


def _file_record(path: Path, output_path: Path) -> Dict:
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(output_path)).replace("\\", "/"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def write_manifest(output_path: Path, config: Dict, privacy_counts: Dict[str, int]) -> Path:
    files = [
        _file_record(path, output_path)
        for path in sorted(output_path.rglob("*"))
        if path.is_file() and path.name != "output_manifest.json"
    ]
    manifest = {
        "character_id": config["character_id"],
        "display_name": config["display_name"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "character-generator",
        "config": {
            key: config[key]
            for key in [
                "language",
                "privacy_level",
                "style_strength",
                "target_tasks",
                "forbidden_tasks",
                "quote_policy",
                "max_quote_chars",
            ]
        },
        "source_planning": {
            "enabled": bool(config.get("source_planning_enabled")),
            "corpus_handoff": bool(config.get("generate_corpus_handoff")),
            "sources": [
                {
                    "source_id": source.get("source_id", ""),
                    "source_type": source.get("source_type", "unknown"),
                    "role": source.get("role", ""),
                    "include": source.get("include", True),
                    "generate_readme": source.get("generate_readme", False),
                }
                for source in config.get("corpus_sources", [])
            ],
            "optional_missing_info": config.get("optional_missing_info", []),
        },
        "privacy": {
            "redaction_counts": privacy_counts,
            "raw_values_included": False,
        },
        "files": files,
    }
    manifest_path = output_path / "output_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    raise SystemExit("Use build_character.py as the public entry point.")
