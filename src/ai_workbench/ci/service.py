"""Persistent CI workflow; native runners and GitHub reads share small public seams."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from ..storage import atomic_json


class CIError(ValueError):
    pass


class CIService:
    def __init__(self, root, checks, repairs, clock=time.time):
        self.root, self.checks, self.repairs = Path(root), checks, repairs
        self.clock, self.lock = clock, threading.RLock()
        self.path = self.root / "state.json"
        self.state = {"version": 1, "settings": {"repositories": [], "agent": "dsh", "model": "", "enabled": False, "poll_seconds": 120}, "jobs": [], "last_scan": None, "error": None}
        if self.path.exists():
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
                if state.get("version") != 1 or not isinstance(state.get("jobs"), list) or not isinstance(state.get("settings"), dict):
                    raise ValueError()
                self.state = state
            except (ValueError, OSError, AttributeError) as error:
                raise CIError("CI 状态文件损坏；已保留原文件") from error
        self.committed = deepcopy(self.state)

    def _save(self):
        try:
            atomic_json(self.path, self.state)
        except OSError:
            self.state = deepcopy(self.committed)
            raise
        self.committed = deepcopy(self.state)

    def configure(self, values):
        with self.lock:
            settings = {**self.state["settings"], **deepcopy(values)}
            if not isinstance(settings.get("agent"), str) or not settings["agent"].strip():
                raise CIError("请选择执行 agent")
            if not isinstance(settings.get("model"), str) or len(settings["model"]) > 200:
                raise CIError("model 格式不正确")
            if type(settings.get("enabled")) is not bool:
                raise CIError("监测开关格式不正确")
            if type(settings.get("poll_seconds")) is not int or not 30 <= settings["poll_seconds"] <= 3600:
                raise CIError("监测间隔应在 30–3600 秒之间")
            repositories = settings.get("repositories")
            if not isinstance(repositories, list) or len(repositories) > 20:
                raise CIError("最多配置 20 个仓库")
            for repository in repositories:
                if not isinstance(repository, dict) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(repository.get("slug", ""))):
                    raise CIError("仓库应为 owner/name")
                if not Path(repository.get("path", "")).is_absolute():
                    raise CIError("本地仓库目录必须为绝对路径")
            self.state["settings"] = settings
            self._save()

    def snapshot(self):
        with self.lock:
            return deepcopy(self.state)

    def poll(self):
        settings = self.snapshot()["settings"]
        discovered = []
        for repository in settings["repositories"]:
            for failure in self.checks.scan(repository):
                if type(failure.get("number")) is not int or failure["number"] < 1 or not re.fullmatch(r"[0-9a-f]{40,64}", str(failure.get("head", ""))):
                    raise CIError("GitHub 返回的 PR 身份无效")
                key = f"{repository['slug']}#{failure['number']}@{failure['head']}"
                discovered.append({**deepcopy(failure), "id": hashlib.sha256(key.encode()).hexdigest()[:24], "repository": deepcopy(repository)})
        with self.lock:
            known = {job["id"] for job in self.state["jobs"]}
            current = {failure["id"] for failure in discovered}
            scanned = {repository["slug"] for repository in settings["repositories"]}
            for job in self.state["jobs"]:
                if job["repository"]["slug"] in scanned:
                    job["current_failure"] = job["id"] in current
                    if not job["current_failure"] and job["status"] in ("detected", "failed", "interrupted"):
                        job["status"] = "cleared"
                    elif job["current_failure"] and job["status"] == "cleared":
                        job["status"] = "detected"
            for failure in discovered:
                for prior in self.state["jobs"]:
                    if prior["repository"]["slug"] == failure["repository"]["slug"] and prior["number"] == failure["number"] and prior["head"] != failure["head"] and prior["status"] != "running":
                        prior["status"] = "superseded"
                if failure["id"] not in known:
                    self.state["jobs"].append({**failure, "status": "detected", "current_failure": True, "detected_at": self.clock(), "result": None})
                    known.add(failure["id"])
            self.state.update(last_scan=self.clock(), error=None)
            self._save()
        return self.snapshot()

    def repair(self, job_id, settings_snapshot=None):
        def find_job():
            value = next((item for item in self.state["jobs"] if item["id"] == job_id), None)
            if value is None:
                raise CIError("找不到该 CI 任务")
            return value
        with self.lock:
            job = find_job()
            request = deepcopy(job)
            settings = deepcopy(self.state["settings"] if settings_snapshot is None else settings_snapshot)
        current = self.checks.scan(request["repository"])
        if not any(row["number"] == request["number"] and row["head"] == request["head"] for row in current):
            with self.lock:
                job = find_job()
                job["status"] = "superseded"
                self._save()
            raise CIError("PR 已变化或失败已消失，请刷新后选择最新任务")
        with self.lock:
            job = find_job()
            if any(item["status"] == "running" for item in self.state["jobs"]):
                raise CIError("已有修复正在运行")
            if job["status"] not in ("detected", "failed", "interrupted"):
                raise CIError("该任务已有结果；请查看补丁或刷新最新 PR")
            request.update(agent=settings["agent"], model=settings["model"], settings=settings)
            job.update(status="running", execution={"agent": request["agent"], "model": request["model"], "started_at": self.clock()})
            self._save()
        directory = self.root / "jobs" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        try:
            result = self.repairs.repair(request, directory)
            if result.get("status") == "patch_ready" and (result.get("test_exit") != 0 or not result.get("patch")):
                raise CIError("没有取得补丁和通过测试的证据")
        except CIError as error:
            result = {"status": "failed", "error": str(error)}
        except Exception:
            result = {"status": "failed", "error": "修复未完成；请检查执行环境和本地任务记录"}
        with self.lock:
            job = find_job()
            stale = any(item["repository"]["slug"] == job["repository"]["slug"] and item["number"] == job["number"] and item["head"] != job["head"] and item.get("current_failure", False) for item in self.state["jobs"])
            job.update(result=result, status="superseded" if stale else result.get("status", "failed"), completed_at=self.clock())
            self._save()
        return self.snapshot()
