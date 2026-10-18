"""Only the packaged character generator can execute; inputs/outputs are copies."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from .files import ChatterError, atomic, inside, io_path, plain_path, tree, uid, write_tree


def prepare(service, request, intake_text):
    task = service.store.get("tasks", request["task_id"])
    if task["kind"] != "generator" or task["status"] != "running" or not service.root:
        raise ChatterError("只有已确认的 Generator 任务能运行角色生成器")
    intake = json.loads(intake_text)
    if not isinstance(intake, dict) or not isinstance(intake.get("material_ids"), list):
        raise ChatterError("生成器需要已附加的材料标识")
    selected = {m["id"]: m for m in request["materials"] if not m["as_skill"]}
    if not intake["material_ids"] or any(m not in selected for m in intake["material_ids"]):
        raise ChatterError("生成器仅能使用本次明确附加的材料")
    directory = io_path(inside(service.root / "staging", task["id"] + "/builder-" + uid()[:12]))
    directory.mkdir(parents=True)
    sources = []
    for material_id in intake["material_ids"]:
        path = inside(directory, "materials/" + material_id + "/material.txt")
        atomic(path, selected[material_id]["text"].encode("utf-8"))
        sources.append({"path": str(path.parent), "explicit": True, "source_type": "work", "role": "primary_style_evidence", "generate_readme": True})
    allowed = {"display_name", "character_id", "target_tasks", "target_interaction_type", "authorization_confirmed", "privacy_boundary_accepted", "style_strength", "personal_profile", "relationship_posture"}
    bounded = {k: v for k, v in intake.items() if k in allowed}
    bounded.update(corpus_sources=sources, output_path="output", source_planning_enabled=True,
                   generate_corpus_handoff=True, generate_reports=True)
    atomic(directory / "intake.json", json.dumps(bounded, ensure_ascii=False).encode("utf-8"))
    return directory


def worker(directory):
    """Fixed packaged entry, not an evaluator for arbitrary Python or commands."""
    directory = plain_path(Path(directory))
    intake = json.loads((directory / "intake.json").read_text(encoding="utf-8"))
    if intake["output_path"] != "output":
        raise ChatterError("生成器输出必须位于该任务副本")
    for source in intake["corpus_sources"]:
        path = plain_path(Path(source["path"]))
        if not path.resolve().is_relative_to(directory.resolve() / "materials"):
            raise ChatterError("生成器输入必须是复制后的任务材料")
    scripts = Path(__file__).with_name("resources") / "generator" / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("chatter_bundled_generator", scripts / "build_character.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config, _ = module.normalize_intake_to_config(intake)
    module.validate_config(config)  # validate against the packaged, immutable schema first
    write_tree(directory / "templates", tree(scripts.parent / "templates"))
    module.PROJECT_ROOT = directory  # all build-relative writes now belong to this task copy
    result = module._run_build(config)
    atomic(directory / "receipt.json", json.dumps({"status": "completed", "files": result["files"], "chunks": result["chunks"]}).encode())


def run(directory, cancelled):
    command = [sys.executable, "--role-worker", str(directory)] if getattr(sys, "frozen", False) else [sys.executable, "-B", "-m", "ai_workbench.e_chatter", "--role-worker", str(directory)]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        import time
        deadline = time.monotonic() + 300
        while process.poll() is None:
            if cancelled.wait(.1) or time.monotonic() > deadline:
                process.terminate()
                process.wait(10)
                raise ChatterError("角色生成器已取消或超时，副本已保留")
        if process.returncode or not (directory / "receipt.json").is_file():
            raise ChatterError("角色生成器未通过校验，请检查材料授权、目标任务和角色名称")
        return tree(directory / "output")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(10)
