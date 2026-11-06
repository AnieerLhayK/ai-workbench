from ai_workbench.ci.service import CIService
import pytest
from subprocess import CompletedProcess
import json
import subprocess
import sys
import threading
import time


class Checks:
    def __init__(self):
        self.head = "a" * 40
        self.failed = True

    def scan(self, repository):
        return [{"number": 12, "head": self.head, "url": "https://github.com/owner/repo/pull/12", "checks": ["unit-tests"]}] if self.failed else []


class Repairs:
    def __init__(self):
        self.requests = []

    def repair(self, request, directory):
        self.requests.append(request)
        return {"status": "patch_ready", "test_exit": 0, "patch": "change.diff"}


def test_discovery_is_deduplicated_and_does_not_start_repairs(tmp_path):
    checks, repairs = Checks(), Repairs()
    service = CIService(tmp_path / "state", checks, repairs)
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}], "agent": "dsh"})
    service.poll()
    service.poll()
    state = service.snapshot()
    assert len(state["jobs"]) == 1
    assert state["jobs"][0]["status"] == "detected"
    assert repairs.requests == []


def test_manual_repair_snapshots_agent_and_rejects_a_moved_head(tmp_path):
    checks, repairs = Checks(), Repairs()
    service = CIService(tmp_path / "state", checks, repairs)
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}], "agent": "claude", "model": "chosen-model"})
    service.poll()
    job = service.snapshot()["jobs"][0]
    service.repair(job["id"])
    assert repairs.requests[0]["agent"] == "claude"
    assert repairs.requests[0]["model"] == "chosen-model"
    assert service.snapshot()["jobs"][0]["status"] == "patch_ready"
    checks.head = "b" * 40
    with pytest.raises(ValueError, match="变化"):
        service.repair(job["id"])
    assert len(repairs.requests) == 1


def test_github_discovery_keeps_only_failed_actions_checks(tmp_path):
    from ai_workbench.ci.github import GitHubChecks
    calls = []
    rows = [{"number": 4, "headRefOid": "c" * 40, "url": "https://github.com/o/r/pull/4", "statusCheckRollup": [
        {"name": "external", "conclusion": "FAILURE", "detailsUrl": "https://buildkite.com/build/1"},
        {"name": "pending", "conclusion": None, "detailsUrl": "https://github.com/o/r/actions/runs/122"},
        {"name": "tests", "conclusion": "FAILURE", "detailsUrl": "https://github.com/O/R/actions/runs/123"},
        {"name": "other", "conclusion": "FAILURE", "detailsUrl": "https://github.com/o/renamed/actions/runs/123"},
        {"name": "lint", "conclusion": "SUCCESS", "detailsUrl": "https://github.com/o/r/actions/runs/124"}]}]
    def run(arguments, **kwargs):
        calls.append(arguments)
        return CompletedProcess(arguments, 0, json.dumps(rows), "")
    source = GitHubChecks(run=run)
    found = source.scan({"slug": "o/r", "path": str(tmp_path)})
    assert found == [{"number": 4, "head": "c" * 40, "url": "https://github.com/o/r/pull/4", "checks": ["tests"]}]
    assert calls[0][:3] == ["gh", "pr", "list"]


def test_repair_runs_in_an_independent_clone_and_produces_a_verified_patch(tmp_path):
    from ai_workbench.ci.repair import NativeRepair
    source = tmp_path / "original"
    source.mkdir()
    (source / "answer.py").write_text("VALUE = 0\n")
    (source / "tests").mkdir()
    (source / "tests" / "测试_用例.py").write_text("# original assertions\n", encoding="utf-8")
    (source / "test_answer.py").write_text("import unittest\nfrom answer import VALUE\nclass TestAnswer(unittest.TestCase):\n def test_value(self): self.assertEqual(VALUE, 1)\n")
    def git(*args):
        return subprocess.run(["git", *args], cwd=source, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=CI Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "failing")
    head = git("rev-parse", "HEAD")
    git("update-ref", "refs/pull/12/head", head)
    class Agent:
        def run(self, workspace, prompt, settings):
            assert workspace != source
            assert "gh-fix-ci" in prompt
            (workspace / "answer.py").write_text("VALUE = 1\n")
            return {"completed": True, "agent": "controlled"}
        def verify(self, workspace, command, settings):
            return subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=30)
    repair = NativeRepair(Agent())
    result = repair.repair({"number": 12, "head": head, "repository": {"slug": "o/r", "path": str(source)}, "agent": "dsh", "model": "", "settings": {"test_command": [sys.executable, "-B", "-m", "unittest", "-v"]}}, tmp_path / "job")
    assert result["status"] == "patch_ready"
    assert result["test_exit"] == 0
    assert "VALUE = 1" in (tmp_path / "job" / result["patch"]).read_text()
    assert (source / "answer.py").read_text() == "VALUE = 0\n"
    assert git("status", "--porcelain") == ""
    class TestChangingAgent:
        def run(self, workspace, prompt, settings):
            (workspace / "answer.py").write_text("VALUE = 1\n")
            (workspace / "tests" / "测试_用例.py").write_text("# changed assertions\n", encoding="utf-8")
            return {"completed": True}
        def verify(self, *args):
            raise AssertionError("Changed tests require review before verification")
    review = NativeRepair(TestChangingAgent()).repair({"number": 12, "head": head, "repository": {"slug": "o/r", "path": str(source)}, "agent": "dsh", "model": "", "settings": {"test_command": [sys.executable, "-B", "-m", "unittest", "-v"]}}, tmp_path / "job2")
    assert review["status"] == "needs_review"
    assert review["review_files"] == ["tests/测试_用例.py"]
    class MutatingVerifier(Agent):
        def verify(self, workspace, command, settings):
            (workspace / "answer.py").write_text("VALUE = 2\n")
            return subprocess.CompletedProcess(command, 0, "passed", "")
    review = NativeRepair(MutatingVerifier()).repair({"number": 12, "head": head, "repository": {"slug": "o/r", "path": str(source)}, "agent": "dsh", "model": "", "settings": {"test_command": [sys.executable, "-B", "-m", "unittest", "-v"]}}, tmp_path / "job3")
    assert review["status"] != "patch_ready"
    class RenamingAgent(Agent):
        def run(self, workspace, prompt, settings):
            (workspace / "tests" / "测试_用例.py").rename(workspace / "renamed.py")
            return {"completed": True}
    review = NativeRepair(RenamingAgent()).repair({"number": 12, "head": head, "repository": {"slug": "o/r", "path": str(source)}, "agent": "dsh", "model": "", "settings": {"test_command": [sys.executable, "-B", "-m", "unittest", "-v"]}}, tmp_path / "job4")
    assert review["status"] == "needs_review"
    assert "tests/测试_用例.py" in review["review_files"]


def test_client_retries_transient_state_read(tmp_path, monkeypatch):
    from ai_workbench.ci.client import CIClient
    import ai_workbench.ci.client as module
    values = iter([{}, {"jobs": [{"id": "one"}]}])
    monkeypatch.setattr(module, "read_json", lambda path: next(values))
    assert CIClient(tmp_path, launch=lambda: None).snapshot()["jobs"][0]["id"] == "one"


def test_worker_keeps_monitoring_after_client_is_replaced(tmp_path):
    from ai_workbench.ci.client import CIClient
    from ai_workbench.ci.worker import serve
    stop = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path, Checks(), Repairs(), stop))
    thread.start()
    client = CIClient(tmp_path, launch=lambda: None)
    def wait_for(predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.03)
        raise AssertionError("worker did not complete request")
    try:
        client.send("configure", values={"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}], "enabled": True})
        client.send("scan")
        wait_for(lambda: bool(client.snapshot().get("jobs")))
        reopened = CIClient(tmp_path, launch=lambda: None)
        del client
        assert reopened.snapshot()["settings"]["enabled"] is True
        initial = reopened.status()["heartbeat"]
        wait_for(lambda: reopened.status().get("heartbeat", 0) > initial)
        assert reopened.snapshot()["jobs"][0]["status"] == "detected"
        reopened.send("repair", job_id=reopened.snapshot()["jobs"][0]["id"])
        wait_for(lambda: reopened.snapshot()["jobs"][0]["status"] == "patch_ready")
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()


def test_native_tool_guard_rejects_remote_writes_and_path_escape(tmp_path):
    from ai_workbench.ci.tool_guard import decision
    policy = {"workspace": str(tmp_path), "skill": str(tmp_path / "skill"), "repository": "owner/repo", "test_command": ["python", "-m", "pytest"]}
    assert decision("pwsh", {"command": "git push origin HEAD"}, policy)
    assert decision("pwsh", {"command": "gh pr merge 12"}, policy)
    assert decision("pwsh", {"command": "gh auth status --show-token"}, policy)
    assert decision("pwsh", {"command": "gh auth status --show-token=true"}, policy)
    assert decision("pwsh", {"command": "gh pr checks 12 --repo=other/repo"}, policy)
    assert decision("pwsh", {"command": "gh pr checks 12 -Rother/repo"}, policy)
    assert decision("pwsh", {"command": "git diff $env:GH_TOKEN"}, policy)
    assert decision("pwsh", {"command": "python -m pytest; git push"}, policy)
    assert decision("write", {"file_path": str(tmp_path.parent / "outside.py")}, policy)
    assert decision("write", {"file_path": str(tmp_path / ".git/config")}, policy)
    assert decision("write", {"file_path": str(tmp_path / ".Git/config")}, policy)
    assert decision("pwsh", {"command": "python -m pytest"}, policy) is None
    assert decision("write", {"file_path": str(tmp_path / "answer.py")}, policy) is None


def test_worker_keeps_a_failed_request_visible_across_heartbeats(tmp_path):
    from ai_workbench.ci.client import CIClient
    from ai_workbench.ci.worker import serve
    stop = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path, Checks(), Repairs(), stop))
    thread.start()
    client = CIClient(tmp_path, launch=lambda: None)
    try:
        request = client.send("configure", values={"repositories": [{"slug": "not-a-slug", "path": str(tmp_path)}]})
        deadline = time.monotonic() + 5
        while not (tmp_path / "receipts" / (request + ".json")).is_file() and time.monotonic() < deadline:
            time.sleep(0.03)
        time.sleep(1.2)
        assert "owner/name" in client.status()["error"]
    finally:
        stop.set()
        thread.join(5)


def test_failed_settings_save_cannot_enable_uncommitted_monitoring(monkeypatch, tmp_path):
    service = CIService(tmp_path, Checks(), Repairs())
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}]})
    def fail(*args):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr("ai_workbench.ci.service.atomic_json", fail)
    with pytest.raises(OSError):
        service.configure({"enabled": True})
    assert service.snapshot()["settings"]["enabled"] is False


def test_monitor_clears_absent_failures_and_detects_same_head_again(tmp_path):
    checks = Checks()
    service = CIService(tmp_path, checks, Repairs())
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}]})
    service.poll()
    checks.failed = False
    service.poll()
    assert service.snapshot()["jobs"][0]["status"] == "cleared"
    checks.failed = True
    service.poll()
    assert len(service.snapshot()["jobs"]) == 1
    assert service.snapshot()["jobs"][0]["status"] == "detected"


def test_a_new_head_observed_during_repair_supersedes_result_even_with_equal_timestamps(tmp_path):
    checks = Checks()
    class ConcurrentRepair:
        def repair(self, request, directory):
            checks.head = "b" * 40
            service.poll()
            return {"status": "patch_ready", "test_exit": 0, "patch": "change.diff"}
    service = CIService(tmp_path, checks, ConcurrentRepair(), clock=lambda: 1)
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}]})
    service.poll()
    initial = service.snapshot()["jobs"][0]["id"]
    service.repair(initial)
    old = next(job for job in service.snapshot()["jobs"] if job["id"] == initial)
    assert old["status"] == "superseded"


def test_known_repair_blocker_is_visible_to_the_user(tmp_path):
    from ai_workbench.ci.service import CIError
    class Blocked:
        def repair(self, request, directory):
            raise CIError("独立测试沙箱不可用")
    service = CIService(tmp_path, Checks(), Blocked())
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}]})
    service.poll()
    job = service.snapshot()["jobs"][0]
    service.repair(job["id"])
    result = service.snapshot()["jobs"][0]
    assert result["status"] == "failed"
    assert result["result"]["error"] == "独立测试沙箱不可用"


def test_repair_uses_the_settings_snapshotted_when_it_was_requested(tmp_path):
    repairs = Repairs()
    service = CIService(tmp_path, Checks(), repairs)
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}], "agent": "claude", "model": "old-model"})
    service.poll()
    saved = service.snapshot()
    service.configure({"agent": "codex", "model": "new-model"})
    service.repair(saved["jobs"][0]["id"], settings_snapshot=saved["settings"])
    assert repairs.requests[0]["agent"] == "claude"
    assert repairs.requests[0]["model"] == "old-model"


def test_failed_worker_configuration_never_starts_the_requested_repair(tmp_path):
    from ai_workbench.ci.client import CIClient
    from ai_workbench.ci.worker import serve
    stop, repairs = threading.Event(), Repairs()
    thread = threading.Thread(target=serve, args=(tmp_path, Checks(), repairs, stop))
    thread.start()
    client = CIClient(tmp_path, launch=lambda: None)
    try:
        client.send("configure", values={"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}]})
        client.send("scan")
        deadline = time.monotonic() + 6
        while not client.snapshot().get("jobs") and time.monotonic() < deadline:
            time.sleep(.03)
        job = client.snapshot()["jobs"][0]
        request = client.send("configure_and_repair", values={"repositories": [{"slug": "invalid", "path": str(tmp_path)}]}, job_id=job["id"])
        receipt = tmp_path / "receipts" / (request + ".json")
        deadline = time.monotonic() + 6
        while not receipt.is_file() and time.monotonic() < deadline:
            time.sleep(.03)
        assert "owner/name" in json.loads(receipt.read_text(encoding="utf-8"))["error"]
        assert repairs.requests == []
        assert client.snapshot()["jobs"][0]["status"] == "detected"
    finally:
        stop.set()
        thread.join(5)


def test_repair_survives_a_concurrent_failed_settings_save(monkeypatch, tmp_path):
    class ChecksWithFailedSave(Checks):
        armed = False
        def scan(self, repository):
            if self.armed:
                self.armed = False
                with monkeypatch.context() as context:
                    def fail(*args):
                        raise OSError("synthetic disk failure")
                    context.setattr("ai_workbench.ci.service.atomic_json", fail)
                    with pytest.raises(OSError):
                        service.configure({"enabled": True})
            return super().scan(repository)
    checks, repairs = ChecksWithFailedSave(), Repairs()
    service = CIService(tmp_path, checks, repairs)
    service.configure({"repositories": [{"slug": "owner/repo", "path": str(tmp_path)}]})
    service.poll()
    job_id = service.snapshot()["jobs"][0]["id"]
    checks.armed = True
    service.repair(job_id)
    assert service.snapshot()["jobs"][0]["status"] == "patch_ready"
    assert len(repairs.requests) == 1
