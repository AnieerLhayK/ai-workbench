import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("projection", ROOT / "scripts/projection.py")
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


def test_preview_complete_portable_and_exact(tmp_path):
    destination = tmp_path / "preview"
    files = projection.export(ROOT, destination)
    assert set(files) == set(projection.allowed_files(ROOT) + projection.GENERATED)
    assert not (destination / "scripts/Archive-Legacy.ps1").exists()
    assert not (destination / "package_manifest.json").exists()
    assert not (destination / "shared/protocol_manifest.json").exists()
    assert (destination / "src/ai_workbench/app.py").exists()
    assert (destination / "src/ai_workbench/catalog.py").exists()
    assert (destination / "skills/ai-workbench-maintainer/SKILL.md").exists()
    with pytest.raises(ValueError, match="empty destination"):
        projection.export(ROOT, destination)
    assert projection.export(ROOT, destination, refresh=True) == files
    (destination / "private.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected"):
        projection.check(destination)
    with pytest.raises(ValueError, match="Unexpected"):
        projection.export(ROOT, destination, refresh=True)


def test_checker_rejects_broken_links_and_machine_paths(tmp_path):
    destination = tmp_path / "preview"
    projection.export(ROOT, destination)
    readme = destination / "README.md"
    original = readme.read_text(encoding="utf-8")
    readme.write_text(original + "\n[bad](../private.md)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Broken or private"):
        projection.check(destination)
    readme.write_text(original + "\n" + "Z:" + "/private/data\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Machine path"):
        projection.check(destination)


def test_no_in_tree_export():
    with pytest.raises(ValueError, match="outside package"):
        projection.export(ROOT, ROOT / "preview")


def test_reject_unsafe_contract(tmp_path):
    (tmp_path / "projection-contract.json").write_text(json.dumps({"files": ["../secret"], "generated_files": projection.GENERATED}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe"):
        projection.allowed_files(tmp_path)


def test_source_marker_public_revision_and_exact_fields(tmp_path):
    destination = tmp_path / "public"
    revision = "a" * 40
    projection.export(ROOT, destination, source_revision=revision)
    assert projection.check(destination, revision, require_revision=True)
    with pytest.raises(ValueError, match="mismatch"):
        projection.check(destination, "b" * 40)
    marker = destination / "PROJECTION_SOURCE.json"
    value = json.loads(marker.read_text())
    value["private_repository"] = "private"
    marker.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="source fields"):
        projection.check(destination)


def test_null_local_marker_and_clone_reexport(tmp_path):
    destination = tmp_path / "preview"
    projection.export(ROOT, destination, source_revision="a" * 40)
    clone_preview = tmp_path / "second"
    projection.export(destination, clone_preview)
    assert projection.check(clone_preview, "a" * 40, require_revision=True)
    (destination / "PROJECTION_SOURCE.json").write_text(json.dumps(projection.provenance()), encoding="utf-8")
    with pytest.raises(ValueError, match="requires"):
        projection.check(destination, require_revision=True)


def test_root_git_metadata_pruned_and_git_staging_explicit(tmp_path):
    destination = tmp_path / "repo"
    (destination / ".git" / "objects").mkdir(parents=True)
    (destination / ".git" / "objects" / "opaque").write_bytes(b"\xff")
    with pytest.raises(ValueError, match="empty destination"):
        projection.export(ROOT, destination)
    projection.export(ROOT, destination, git_staging=True)
    assert projection.check(destination)
    (destination / "src" / ".git").mkdir()
    (destination / "src" / ".git" / "secret").write_text("private")
    with pytest.raises(ValueError, match="Unexpected"):
        projection.check(destination)


def test_forbidden_payload_and_missing_allowed_file(tmp_path):
    destination = tmp_path / "public"
    projection.export(ROOT, destination)
    (destination / "README.md").unlink()
    with pytest.raises(ValueError, match="Missing"):
        projection.check(destination)
    projection.export(ROOT, tmp_path / "other")
    (tmp_path / "other" / "config.json").write_text("{}")
    with pytest.raises(ValueError, match="Unexpected"):
        projection.check(tmp_path / "other")


def test_authoritative_inventory_cannot_be_replaced(tmp_path):
    destination = tmp_path / "public"
    files = projection.export(ROOT, destination)
    contract_path = destination / "projection-contract.json"
    contract = json.loads(contract_path.read_text())
    contract["files"].remove("README.md")
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="authoritative contract"):
        projection.check(destination, expected_files=files)
