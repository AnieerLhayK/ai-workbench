"""Build a self-contained Windows directory; all build scratch stays external."""
import argparse
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import runpy
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    staging, output = args.staging.resolve(), args.output.resolve()
    if staging == package or staging.is_relative_to(package):
        parser.error("build staging must be outside the source tree")
    if output == package or output.is_relative_to(package):
        parser.error("release output must be outside the source tree")
    web = package / "src/ai_workbench/e_chatter/web"
    if not (web / "index.html").is_file():
        parser.error("run npm ci and npm run build in frontend/e-chatter first")
    version = runpy.run_path(str(web.parent / "__init__.py"))["VERSION"]
    frontend_version = json.loads((package / "frontend/e-chatter/package.json").read_text(encoding="utf-8"))["version"]
    if version != frontend_version:
        parser.error("application/frontend versions differ")
    inputs = [p for folder in (web, web.parent / "resources") for p in folder.rglob("*") if p.is_file()]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    staging.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ | {"PYINSTALLER_CONFIG_DIR": str(staging / "cache")}
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
                    "--name", "e-Chatter", "--distpath", str(output), "--workpath", str(staging / "work"),
                    "--specpath", str(staging), "--paths", str(package / "src"),
                    "--add-data", f"{web};ai_workbench/e_chatter/web",
                    "--add-data", f"{web.parent / 'resources'};ai_workbench/e_chatter/resources",
                    "--exclude-module", "numpy", "--exclude-module", "pandas", "--exclude-module", "matplotlib",
                    "--exclude-module", "IPython", "--exclude-module", "torch",
                    "--exclude-module", "__main__",
                    str(package / "scripts/launch_e_chatter.py")], check=True, env=environment)
    release = output / "e-Chatter"
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(release / "e-Chatter.exe")).open_embedded_archive("PYZ.pyz")
    def code_shape(code):
        return (code.co_code, code.co_names, code.co_varnames,
                tuple(code_shape(value) if isinstance(value, types.CodeType) else value for value in code.co_consts))
    modules = ["ai_workbench.codex_isolation", *(
        "ai_workbench.e_chatter." + name for name in ("app", "builder", "codex", "providers", "deepseek", "harness_archive", "files", "migration", "service", "store"))]
    for module in modules:
        source = package / "src" / (module.replace(".", "/") + ".py")
        expected = compile(source.read_text(encoding="utf-8"), str(source), "exec")
        if code_shape(archive.extract(module)) != code_shape(expected):
            raise RuntimeError("Frozen module differs from current source: " + module)
    for source, expected in hashes.items():
        frozen = release / "_internal" / "ai_workbench/e_chatter" / source.relative_to(web.parent)
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected or not frozen.is_file() or hashlib.sha256(frozen.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Packaged resource differs from build input: " + str(source.relative_to(package)))
    (release / "BUILD.json").write_text(json.dumps({"version": version, "platform": "windows-x64", "resources": {str(p.relative_to(web.parent)).replace("\\", "/"): value for p, value in hashes.items()}}, indent=2) + "\n", encoding="utf-8")
    for name in ("LICENSE",):
        (release / name).write_bytes((package / name).read_bytes())
    (release / "README.md").write_bytes((package / "docs/e-chatter.md").read_bytes())
    licenses = release / "licenses"
    licenses.mkdir(exist_ok=True)
    for distribution in ("PySide6", "shiboken6", "PyYAML", "PyInstaller"):
        metadata = importlib.metadata.distribution(distribution)
        for item in metadata.files or []:
            if any(word in item.name.lower() for word in ("license", "copying", "notice")):
                source = Path(metadata.locate_file(item))
                if source.is_file():
                    (licenses / (distribution + "-" + source.name)).write_bytes(source.read_bytes())
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        (licenses / "Python-LICENSE.txt").write_bytes(python_license.read_bytes())
    nodes = package / "frontend/e-chatter/node_modules"
    pending, seen = list(json.loads((nodes.parent / "package.json").read_text())["dependencies"]), set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        source = nodes / name
        manifest = json.loads((source / "package.json").read_text(encoding="utf-8"))
        pending.extend(manifest.get("dependencies", {}))
        for file in source.iterdir():
            if file.is_file() and file.name.lower().startswith(("license", "copying", "notice")):
                (licenses / (name.replace("/", "-") + "-" + file.name)).write_bytes(file.read_bytes())
    for file in (package / "docs/e-chatter-licenses").glob("*"):
        (licenses / file.name).write_bytes(file.read_bytes())
    with zipfile.ZipFile(output / "e-Chatter-windows-x64.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in release.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(output))


if __name__ == "__main__":
    main()
