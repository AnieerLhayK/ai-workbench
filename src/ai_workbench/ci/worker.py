"""Detached single-writer CI worker. Closing a window does not stop monitoring."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

from ..storage import ProcessLock, atomic_json
from .github import GitHubChecks
from .service import CIService, CIError


def serve(root, checks=None, repairs=None, stop=None):
    root = Path(root)
    lock = ProcessLock(root / "worker.lock")
    if not lock.acquired:
        return
    pool = ThreadPoolExecutor(max_workers=1)
    active = None
    last_scan = 0
    error = None
    last_heartbeat = 0
    previous_status = None
    try:
        if repairs is None:
            from .agents import NativeAgent
            from .repair import NativeRepair
            repairs = NativeRepair(NativeAgent())
        service = CIService(root, checks or GitHubChecks(), repairs)
        with service.lock:
            recovered = False
            for job in service.state["jobs"]:
                if job["status"] == "running":
                    job.update(status="interrupted", result={"error": "上次执行已中断，未自动重试"})
                    recovered = True
            if recovered:
                service._save()
        commands = root / "commands"
        commands.mkdir(exist_ok=True)
        while stop is None or not stop.is_set():
            for path in sorted(commands.glob("*.json"))[:50]:
                try:
                    error = None
                    if path.stat().st_size > 65536:
                        raise CIError("请求过大")
                    command = json.loads(path.read_text(encoding="utf-8"))
                    action = command["action"]
                    if action in ("configure", "configure_and_scan", "configure_and_repair"):
                        if action == "configure_and_repair" and active is not None and not active.done():
                            raise CIError("已有修复正在运行")
                        service.configure(command["values"])
                        if action == "configure_and_scan":
                            service.poll()
                            last_scan = time.monotonic()
                        elif action == "configure_and_repair":
                            settings_snapshot = service.snapshot()["settings"]
                            active = pool.submit(service.repair, command["job_id"], settings_snapshot)
                    elif action == "scan":
                        service.poll()
                        last_scan = time.monotonic()
                    elif action == "repair":
                        if active is not None and not active.done():
                            raise CIError("已有修复正在运行")
                        active = pool.submit(service.repair, command["job_id"], service.snapshot()["settings"])
                    else:
                        raise CIError("不支持的 CI 操作")
                except Exception as failure:
                    error = str(failure) if isinstance(failure, CIError) else "CI 请求未完成"
                finally:
                    atomic_json(root / "receipts" / path.name, {"error": error, "completed_at": time.time()})
                    path.unlink()
            if active is not None and active.done():
                try:
                    active.result()
                except Exception as failure:
                    error = str(failure) if isinstance(failure, CIError) else "CI 修复未完成"
                active = None
            state = service.snapshot()
            if state["settings"]["enabled"] and time.monotonic() - last_scan >= state["settings"]["poll_seconds"]:
                try:
                    service.poll()
                    error = None
                except Exception as failure:
                    error = str(failure) if isinstance(failure, CIError) else "GitHub 扫描失败"
                last_scan = time.monotonic()
            current_status = {"monitoring": state["settings"]["enabled"], "repairing": active is not None, "error": error}
            if current_status != previous_status or time.monotonic() - last_heartbeat >= 5:
                atomic_json(root / "worker-status.json", {"heartbeat": time.time(), **current_status})
                previous_status = current_status
                last_heartbeat = time.monotonic()
            time.sleep(0.5)
    finally:
        pool.shutdown(wait=True)
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    try:
        serve(args.root)
    except Exception as error:
        atomic_json(args.root / "worker-status.json", {"heartbeat": time.time(), "error": "CI 后台无法启动；原状态文件已保留", "error_code": type(error).__name__, "monitoring": False})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
