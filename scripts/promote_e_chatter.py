"""Manual, local-only promotion of committed e-Chatter source and one artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid
import zipfile


PACKAGE = Path(__file__).resolve().parents[1]
REQUIRED_ACCEPTANCE = ("codex_real", "deepseek_account_real", "deepseek_key_real", "clean_windows11")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(p in ("..", ".git") for p in path.parts) or ":" in name or "\\" in name or path.as_posix() != name:
        raise ValueError("Unsafe payload path")
    return name


def unlinked(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
            raise ValueError("Linked promotion paths are not allowed")
    return path.resolve()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class Source:
    """Only immutable Git blobs cross the snapshot seam."""
    def __init__(self, package, revision, version):
        self.package = unlinked(package)
        self.root = Path(self.git("rev-parse", "--show-toplevel").decode().strip())
        self.prefix = self.package.relative_to(self.root).as_posix()
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Use a full 40-character committed source revision")
        self.revision = self.git("rev-parse", "--verify", revision + "^{commit}").decode().strip()
        if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-rc\.[1-9]\d*)?", version):
            raise ValueError("Expected major.minor.patch or major.minor.patch-rc.N")
        self.version = version
        self.contract = json.loads(self.blob("distribution/e-chatter/contract.json"))
        paths = self.git("ls-tree", "-r", "-z", self.revision, "--", self.prefix).decode().split("\0")
        self.tracked = {}
        for row in filter(None, paths):
            metadata, name = row.split("\t", 1)
            self.tracked[name[len(self.prefix) + 1:]] = metadata.split()[0]
        self.mapping = dict(self.contract["files"])
        for origin, destination in self.contract["trees"].items():
            for name in self.tracked:
                if name.startswith(origin + "/"):
                    tail = PurePosixPath(name).relative_to(origin)
                    if any(p in self.contract["excluded_parts"] for p in tail.parts):
                        continue
                    if name in self.mapping:
                        raise ValueError("Overlapping payload selections")
                    self.mapping[name] = (PurePosixPath(destination) / tail).as_posix()
        if len(set(self.mapping.values())) != len(self.mapping):
            raise ValueError("Duplicate snapshot destinations")
        self.payload = {}
        for name, destination in self.mapping.items():
            relative(name), relative(destination)
            if self.tracked.get(name) not in ("100644", "100755"):
                raise ValueError("Missing or linked source input: " + name)
            if PurePosixPath(destination).suffix in self.contract["forbidden_suffixes"]:
                raise ValueError("Forbidden snapshot file")
            self.payload[destination] = self.blob(name)
        app = self.payload["src/ai_workbench/e_chatter/__init__.py"].decode()
        match = re.search(r'^VERSION = "([^"]+)"', app, re.M)
        front = json.loads(self.payload["frontend/e-chatter/package.json"])
        lock = json.loads(self.payload["frontend/e-chatter/package-lock.json"])
        project = tomllib.loads(self.payload["pyproject.toml"].decode())
        if not match or {match[1], front["version"], lock["version"], lock["packages"][""]["version"], project["project"]["version"]} != {version}:
            raise ValueError("Source, frontend, lockfile and independent project versions must match")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(getattr(self, "root", self.package)), *args], check=True, capture_output=True).stdout

    def blob(self, name):
        relative(name)
        return self.git("show", self.revision + ":" + self.prefix + "/" + name)

    def require_clean(self):
        selected = [self.prefix + "/" + name for name in self.mapping]
        selected += [self.prefix + "/distribution/e-chatter/contract.json", self.prefix + "/scripts/promote_e_chatter.py"]
        # Include trees so untracked source files cannot silently disappear.
        selected += [self.prefix + "/" + name for name in self.contract["trees"]]
        dirty = self.git("status", "--porcelain", "--untracked-files=all", "--", *selected)
        changed = self.git("diff", "--name-only", self.revision, "--", *selected)
        if dirty.strip() or changed.strip():
            raise ValueError("Selected development inputs are dirty or differ from the selected commit")

    def export(self, target):
        target.mkdir(parents=True, exist_ok=False)
        for name, content in self.payload.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def acceptance(path, revision, version):
    value = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    if value and (value.get("source_revision") != revision or value.get("version") != version):
        raise ValueError("Acceptance receipt does not match source revision/version")
    checks = value.get("checks", {})
    passed = [name for name in REQUIRED_ACCEPTANCE if checks.get(name, {}).get("passed") is True and isinstance(checks[name].get("evidence"), str) and checks[name]["evidence"].strip()]
    missing = [name for name in REQUIRED_ACCEPTANCE if name not in passed]
    if "-rc." not in version and missing:
        raise ValueError("Stable release blocked by missing acceptance: " + ", ".join(missing))
    # Receipts stay external; snapshots carry check names, not arbitrary private text.
    return {"passed": passed, "missing": missing, "status": "candidate" if "-rc." in version else "stable"}


def verify_payload(directory, expected):
    for path in directory.rglob("*"):
        unlinked(path)
    actual = {p.relative_to(directory).as_posix(): sha(p.read_bytes()) for p in directory.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("Snapshot payload inventory/hash mismatch")


def activate(staged, target, development_receipts, manifest):
    """Immutable version first; pointer last. Old active version survives failure."""
    target, development_receipts = unlinked(target), unlinked(development_receipts)
    version = manifest["version"]
    final = target / "versions" / version
    receipt = development_receipts / (version + ".json")
    if final.exists() or receipt.exists():
        raise ValueError("Version already exists; choose a new version")
    expected = manifest["files"]
    verify_payload(staged, expected | {"SNAPSHOT.json": sha((staged / "SNAPSHOT.json").read_bytes())})
    incoming = target / "versions" / (".incoming-" + uuid.uuid4().hex)
    incoming.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staged, incoming)
    verify_payload(incoming, expected | {"SNAPSHOT.json": sha((staged / "SNAPSHOT.json").read_bytes())})
    os.replace(incoming, final)
    pointer = {"version": version, "status": manifest["acceptance"]["status"], "source_revision": manifest["source_revision"], "snapshot": "versions/" + version, "artifact": manifest["artifact"]}
    write_json(receipt, pointer)
    write_json(target / ("candidate.json" if "-rc." in version else "stable.json"), pointer)
    return pointer


def build_environment():
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "E_CHATTER_RUN_NATIVE", "E_CHATTER_RUN_DSH"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    if os.name == "nt":
        # Qt's renderer launch needs the native Windows Path spelling. An
        # explicit upper-case PATH environment can omit DLL search propagation.
        value = env.pop("PATH", "")
        env["Path"] = value
    return env


def run_checks(directory, build_python, staging, output):
    env = build_environment()
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise ValueError("Node/npm is required for maintainers to build, not for end users")
    def run(args, cwd=directory, extra=None):
        subprocess.run([str(a) for a in args], cwd=cwd, env=env | (extra or {}), check=True)
    run([npm, "ci", "--no-audit", "--no-fund"], directory / "frontend/e-chatter")
    run([npm, "test"], directory / "frontend/e-chatter")
    run([npm, "run", "build"], directory / "frontend/e-chatter")
    installed = staging / "installed"
    run([build_python, "-B", "-m", "pip", "install", "--no-index", "--no-deps", "--no-build-isolation", "--target", installed, "."])
    run([build_python, "-I", "-c", "import sys,pathlib; root=pathlib.Path(sys.argv[1]).resolve(); sys.path.insert(0,str(root)); import ai_workbench.e_chatter.app as app; assert pathlib.Path(app.__file__).resolve().is_relative_to(root)", installed], staging)
    run([build_python, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests", "--basetemp", staging / "tests"])
    if os.name == "nt":
        run([build_python, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_e_chatter_qt.py", "--basetemp", staging / "native"], extra={"E_CHATTER_RUN_NATIVE": "1"})
    else:
        raise ValueError("Windows x64 build and native verification require Windows")
    run([build_python, "-B", "scripts/build_e_chatter.py", "--staging", staging / "freeze", "--output", output])
    smoke_env = {k: v for k, v in env.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    for key in list(smoke_env):
        if key.casefold() == "path":
            del smoke_env[key]
    system_root = next(value for key, value in env.items() if key.casefold() == "systemroot")
    smoke_env["Path"] = os.path.join(system_root, "System32") + os.pathsep + system_root
    subprocess.run([str(output / "e-Chatter/e-Chatter.exe"), "--demo", "--smoke-exit-ms", "4000"], env=smoke_env, cwd=output, check=True, timeout=40)


def promote(source, target, staging, output, build_python, receipt=None, execute=False):
    target, staging, output = map(unlinked, (target, staging, output))
    if any(p == source.root or p.is_relative_to(source.root) for p in (staging, output)):
        raise ValueError("Staging and release output must be outside the source repository")
    if target == source.package or target.is_relative_to(source.package) or any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for a, b in ((staging, output), (staging, target), (output, target))):
        raise ValueError("Source, staging, output and target paths must not overlap")
    source.require_clean()
    development_receipts = source.package / "distribution/e-chatter/releases"
    final_output = output / source.version
    if (target / "versions" / source.version).exists() or (development_receipts / (source.version + ".json")).exists() or final_output.exists():
        raise ValueError("Version already exists; choose a new version")
    gates = acceptance(receipt, source.revision, source.version)
    preview = {"version": source.version, "source_revision": source.revision, "files": len(source.payload), "acceptance": gates, "execute": execute}
    if not execute:
        return preview
    # Require prior accepted local integration, never export unreviewed working files.
    source.git("merge-base", "--is-ancestor", source.revision, "main")
    staging.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="e-chatter-", dir=staging))
    snapshot = work / "source"
    source.export(snapshot)
    # Build outputs stay in work until all checks pass. No active pointer changes yet.
    built = work / "artifact"
    run_checks(snapshot, build_python, work, built)
    for name, content in source.payload.items():
        if (snapshot / name).read_bytes() != content:
            raise ValueError("Build changed a source input: " + name)
    bundle = built / "e-Chatter-windows-x64.zip"
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupt portable ZIP")
        info = json.loads(archive.read("e-Chatter/BUILD.json"))
        if info["version"] != source.version:
            raise ValueError("Portable version mismatch")
    # Only declared source plus generated frontend enters the durable snapshot.
    clean = work / "snapshot"
    source.export(clean)
    generated = source.contract["generated_tree"]
    shutil.copytree(snapshot / generated, clean / generated)
    inventory = {p.relative_to(clean).as_posix(): sha(p.read_bytes()) for p in clean.rglob("*") if p.is_file()}
    artifact = {"filename": "e-Chatter-windows-x64.zip", "relative_path": source.version + "/e-Chatter-windows-x64.zip", "sha256": sha(bundle.read_bytes()), "bytes": bundle.stat().st_size}
    resolved = json.loads(subprocess.check_output([str(build_python), "-I", "-c", "import sys,json,importlib.metadata as m; print(json.dumps({'python':sys.version.split()[0],**{n:m.version(n) for n in ('PySide6','PyYAML','PyInstaller')}}))"], cwd=work))
    manifest = {"schema_version": 1, "version": source.version, "source_revision": source.revision, "source_package": "packages/ai-workbench", "platform": "windows11-x64", "files": inventory, "artifact": artifact, "acceptance": gates, "checks": {"independent_install": "passed", "frontend": "passed", "controlled_tests": "passed", "native": "passed", "frozen_modules_and_resources": "passed", "restricted_path_demo": "passed"}, "dependencies": {"required": tomllib.loads(source.payload["pyproject.toml"].decode())["project"]["dependencies"], "resolved": resolved, "frontend_lock_sha256": sha(source.payload["frontend/e-chatter/package-lock.json"])}, "resource_provenance": json.loads(source.payload["src/ai_workbench/e_chatter/resources/engineering-source.json"])}
    write_json(clean / "SNAPSHOT.json", manifest)
    (built / "SHA256SUMS").write_text(artifact["sha256"] + "  " + artifact["filename"] + "\n", encoding="ascii")
    write_json(built / "release.json", manifest)
    final_output.parent.mkdir(parents=True, exist_ok=True)
    if final_output.exists():
        raise ValueError("Release output appeared concurrently")
    os.rename(built, final_output)
    if sha((final_output / artifact["filename"]).read_bytes()) != artifact["sha256"]:
        raise ValueError("Published local artifact hash mismatch")
    source.require_clean()
    result = activate(clean, target, development_receipts, manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preview", "execute"))
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", type=Path, default=PACKAGE.parent / "character-system/applications/e-chatter")
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--acceptance", type=Path)
    args = parser.parse_args()
    try:
        value = promote(Source(PACKAGE, args.source_revision, args.version), args.target, args.staging, args.output, args.build_python, args.acceptance, args.mode == "execute")
        print(json.dumps(value, ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        parser.exit(1, "Promotion stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
