"""Promotion tests never build binaries or access accounts."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


spec = importlib.util.spec_from_file_location("promote_e_chatter", Path(__file__).parents[1] / "scripts/promote_e_chatter.py")
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "repo"
    package = root / "packages/ai-workbench"
    version = "0.2.0-rc.1"
    files = {
        "src/ai_workbench/e_chatter/__init__.py": f'VERSION = "{version}"\n',
        "frontend/e-chatter/package.json": json.dumps({"version": version}),
        "frontend/e-chatter/package-lock.json": json.dumps({"version": version, "packages": {"": {"version": version}}}),
        "distribution/e-chatter/pyproject.toml": f'[project]\nversion = "{version}"\n',
    }
    mapping = {name: name for name in files}
    mapping["distribution/e-chatter/pyproject.toml"] = "pyproject.toml"
    contract = {"files": mapping, "trees": {"src/ai_workbench/e_chatter": "src/ai_workbench/e_chatter"}, "excluded_parts": ["web"], "forbidden_suffixes": [".db"], "generated_tree": "src/ai_workbench/e_chatter/web"}
    # Avoid overlapping selection while retaining an untracked-tree check.
    del contract["files"]["src/ai_workbench/e_chatter/__init__.py"]
    files["distribution/e-chatter/contract.json"] = json.dumps(contract)
    for name, text in files.items():
        p = package / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout.decode().strip()
    git("init", "-b", "main")
    git("add", ".")
    git("-c", "user.email=synthetic@example.invalid", "-c", "user.name=Synthetic", "commit", "-m", "fixture")
    return promotion.Source(package, git("rev-parse", "HEAD"), version)


def test_preview_reads_committed_source_without_creating_output(source, tmp_path):
    target, staging, output = (tmp_path / n for n in ("target", "stage", "out"))
    result = promotion.promote(source, target, staging, output, "unused")
    assert result["acceptance"]["status"] == "candidate" and not result["execute"]
    assert not any(p.exists() for p in (target, staging, output))


@pytest.mark.parametrize("change", ["tracked", "untracked"])
def test_dirty_inputs_refuse_before_build(source, tmp_path, change):
    path = source.package / "src/ai_workbench/e_chatter" / ("__init__.py" if change == "tracked" else "new.py")
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty"):
        promotion.promote(source, tmp_path / "target", tmp_path / "stage", tmp_path / "out", "unused", execute=True)
    assert not (tmp_path / "stage").exists()


def test_reused_version_is_not_overwritten(source, tmp_path):
    target = tmp_path / "target"
    (target / "versions" / source.version).mkdir(parents=True)
    with pytest.raises(ValueError, match="already exists"):
        promotion.promote(source, target, tmp_path / "stage", tmp_path / "out", "unused")


def test_source_version_must_match(source):
    with pytest.raises(ValueError, match="versions must match"):
        promotion.Source(source.package, source.revision, "0.2.0-rc.2")


def test_build_failure_leaves_active_snapshot_and_data_unchanged(source, tmp_path, monkeypatch):
    target = tmp_path / "target"
    promotion.write_json(target / "stable.json", {"version": "0.1.0"})
    data = tmp_path / "user-data.txt"
    data.write_text("existing synthetic library", encoding="utf-8")
    before = (target / "stable.json").read_bytes(), data.read_bytes()
    def fail(*args):
        raise ValueError("synthetic failed test")
    monkeypatch.setattr(promotion, "run_checks", fail)
    with pytest.raises(ValueError, match="failed test"):
        promotion.promote(source, target, tmp_path / "stage", tmp_path / "out", "unused", execute=True)
    assert before == ((target / "stable.json").read_bytes(), data.read_bytes())
    assert not (target / "versions").exists()


def staged_snapshot(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "README.md").write_bytes(b"synthetic")
    manifest = {"version": "0.2.0-rc.1", "source_revision": "a" * 40, "files": {"README.md": promotion.sha(b"synthetic")}, "artifact": {"sha256": "b" * 64}, "acceptance": {"status": "candidate"}}
    promotion.write_json(staged / "SNAPSHOT.json", manifest)
    return staged, manifest


def test_candidate_activation_shares_artifact_and_preserves_stable(tmp_path):
    staged, manifest = staged_snapshot(tmp_path)
    target, receipts = tmp_path / "target", tmp_path / "receipts"
    promotion.write_json(target / "stable.json", {"version": "0.1.0"})
    previous = (target / "stable.json").read_bytes()
    result = promotion.activate(staged, target, receipts, manifest)
    assert json.loads((target / "candidate.json").read_text()) == json.loads((receipts / "0.2.0-rc.1.json").read_text()) == result
    assert result["artifact"] == manifest["artifact"]
    assert (target / "stable.json").read_bytes() == previous
    with pytest.raises(ValueError, match="already exists"):
        promotion.activate(staged, target, receipts, manifest)


def test_activation_failure_preserves_current_pointer(tmp_path, monkeypatch):
    staged, manifest = staged_snapshot(tmp_path)
    target, receipts = tmp_path / "target", tmp_path / "receipts"
    promotion.write_json(target / "candidate.json", {"version": "previous"})
    before = (target / "candidate.json").read_bytes()
    def fail(*args):
        raise OSError("synthetic save failure")
    monkeypatch.setattr(promotion, "write_json", fail)
    with pytest.raises(OSError):
        promotion.activate(staged, target, receipts, manifest)
    assert (target / "candidate.json").read_bytes() == before


def test_changed_snapshot_is_rejected(tmp_path):
    staged, manifest = staged_snapshot(tmp_path)
    (staged / "README.md").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        promotion.activate(staged, tmp_path / "target", tmp_path / "receipts", manifest)


def test_stable_requires_matching_real_acceptance(tmp_path):
    with pytest.raises(ValueError, match="missing acceptance"):
        promotion.acceptance(None, "a" * 40, "0.2.0")
    receipt = tmp_path / "acceptance.json"
    value = {"source_revision": "a" * 40, "version": "0.2.0", "checks": {name: {"passed": True, "evidence": "Synthetic test of receipt validation only"} for name in promotion.REQUIRED_ACCEPTANCE}}
    receipt.write_text(json.dumps(value), encoding="utf-8")
    assert not promotion.acceptance(receipt, "a" * 40, "0.2.0")["missing"]
    with pytest.raises(ValueError, match="does not match"):
        promotion.acceptance(receipt, "b" * 40, "0.2.0")


def test_unsafe_paths_and_source_output_overlap_are_refused(source, tmp_path):
    with pytest.raises(ValueError, match="Unsafe"):
        promotion.relative("../credentials.yaml")
    with pytest.raises(ValueError, match="outside"):
        promotion.promote(source, tmp_path / "target", source.package / "staging", tmp_path / "out", "unused")


def test_check_launch_keeps_windows_native_path_spelling(tmp_path, monkeypatch):
    if promotion.os.name != "nt":
        pytest.skip("Windows Qt renderer DLL environment")
    monkeypatch.setenv("PYTHONPATH", "synthetic-source-leak")
    monkeypatch.setattr(promotion.shutil, "which", lambda name: "synthetic-npm.cmd")
    observed = []
    def launch(*args, **kwargs):
        observed.append(kwargs["env"])
        raise RuntimeError("stop before executing fixture command")
    monkeypatch.setattr(promotion.subprocess, "run", launch)
    with pytest.raises(RuntimeError, match="fixture command"):
        promotion.run_checks(tmp_path, "synthetic-python", tmp_path, tmp_path)
    assert "Path" in observed[0] and "PATH" not in observed[0]
    assert "PYTHONPATH" not in observed[0]
