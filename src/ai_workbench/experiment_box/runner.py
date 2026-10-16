"""Detached, one-shot sandbox Runner. Unsupported isolation fails closed."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import threading
from uuid import uuid4

from ..e_diary.codex import AppServer, RpcError, argv
from ..storage import ProcessLock
from .model import StoreError, TrialStore, timestamp, REQUEST_LABELS
from .service import ExperimentService, confined, manifest


def command(config, plan):
    key = "python" if plan["runtime"] == "python" else "powershell"
    executable = Path(config.get(key, ""))
    if not executable.is_absolute() or not executable.is_file():
        raise StoreError("缺少已登记的运行环境：" + key)
    if key == "python":
        return [str(executable), "-I", "-B", "-X", "utf8", plan["script"]]
    invocation = "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); $OutputEncoding = [Console]::OutputEncoding; & './" + plan["script"].replace("'", "''") + "'"
    return [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", invocation]


class WindowsSandbox:
    def __init__(self, config):
        self.config = config
        self.profile_transport = False

    def verify_protocol(self, staging):
        if os.name != "nt":
            raise StoreError("自动运行需要原生 Windows elevated 沙箱")
        result = subprocess.run(argv(self.config["codex_cli"], "app-server", "generate-json-schema", "--experimental", "--out", str(staging)),
                                capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        path = staging / "v2" / "CommandExecParams.json"
        if result.returncode or not path.is_file():
            raise StoreError("无法验证 Codex 沙箱协议，自动运行已阻止")
        value = json.loads(path.read_text(encoding="utf-8"))
        variants = value.get("definitions", {}).get("SandboxPolicy", {}).get("oneOf", [])
        workspace = next((v for v in variants if v.get("properties", {}).get("type", {}).get("enum") == ["workspaceWrite"]), {})
        self.profile_transport = "permissionProfile" in value.get("properties", {})
        if "readOnlyAccess" not in workspace.get("properties", {}) and not self.profile_transport:
            raise StoreError("当前 Codex 缺少限定读取范围接口；自动运行已禁用，请更新后重新验证")

    def execute(self, arguments, root, seconds, cancelled):
        readable = [str(root), str(Path(arguments[0]).parent)]
        policy = dict(type="workspaceWrite", writableRoots=[str(root)],
                      readOnlyAccess=dict(type="restricted", includePlatformDefaults=True, readableRoots=readable),
                      networkAccess=False, excludeTmpdirEnvVar=True, excludeSlashTmp=True)
        # Explicit MXC fails when unsupported; prefer_mxc would allow a legacy
        # fallback and therefore cannot establish this application's boundary.
        options = ("-c", 'windows.sandbox="mxc"', "-c", "features.daemon_auto_start=false",
                   "-c", "features.hooks=false", "-c", "mcp_servers={}")
        process_id = str(uuid4())
        parameters = dict(command=arguments, cwd=str(root), timeoutMs=seconds * 1000, processId=process_id)
        if self.profile_transport:
            # Named native profiles express the same deny-by-default read/write
            # policy on CLI versions whose legacy SandboxPolicy omits read roots.
            filesystem = {":root": "deny", ":minimal": "read", ":tmpdir": "deny", ":slash_tmp": "deny",
                          str(root): "write", str(Path(arguments[0]).parent): "read"}
            table = "{" + ",".join(json.dumps(k) + "=" + json.dumps(v) for k, v in filesystem.items()) + "}"
            options += ("-c", "permissions.experiment-box.filesystem=" + table,
                        "-c", "permissions.experiment-box.network.enabled=false",
                        "-c", 'default_permissions="experiment-box"')
            parameters["permissionProfile"] = "experiment-box"
        else:
            parameters["sandboxPolicy"] = policy
        server = AppServer(self.config["codex_cli"], root, options=options, client_name="experiment_box_runner", experimental=self.profile_transport)
        cancel_sent = False
        def cancel_if_requested():
            nonlocal cancel_sent
            if cancelled.is_set() and not cancel_sent:
                server.send_request("command/exec/terminate", {"processId": process_id})
                cancel_sent = True
        try:
            return server.request("command/exec", parameters, timeout=seconds + 20, on_poll=cancel_if_requested)
        except RpcError as error:
            if "requires effective `:root` read access" in error.detail:
                raise StoreError("此 Codex elevated 沙箱要求全盘读取，无法满足限定读取边界；自动运行已禁用") from error
            raise StoreError("原生沙箱拒绝执行；没有降级或自动重试") from error
        finally:
            server.close()

    def probe(self, root, cancelled):
        """Controlled files only: require outside read/write and child denial,
        plus outbound socket denial before any user script is executed.
        """
        probe_parent = root.parent / (".probe-" + str(uuid4()))
        probe_parent.mkdir(parents=True)
        outside = probe_parent / "outside.txt"
        outside.write_text("isolated-probe", encoding="utf-8")
        probe_root = probe_parent / "allowed"
        probe_root.mkdir()
        source = r'''
import json,pathlib,socket,subprocess,sys
outside=pathlib.Path(sys.argv[1])
checks={}
for operation in ('read','write'):
 try:
  outside.read_text() if operation=='read' else outside.write_text('escape')
  checks[operation]=False
 except OSError: checks[operation]=True
try:
 socket.create_connection(('1.1.1.1',443),timeout=3).close(); checks['network']=False
except OSError: checks['network']=True
pathlib.Path('inside.txt').write_text('ok')
checks['inside']=pathlib.Path('inside.txt').read_text()=='ok'
try:
 socket.create_connection(('127.0.0.1',int(sys.argv[2])),timeout=3).close(); checks['loopback']=False
except OSError: checks['loopback']=True
child_code=r"""import json,pathlib,socket,sys
checks={}
outside=pathlib.Path(sys.argv[1])
for action in ('read','write'):
 try:
  outside.read_text() if action=='read' else outside.write_text('escape')
  checks[action]=False
 except OSError: checks[action]=True
try:
 socket.create_connection(('127.0.0.1',int(sys.argv[2])),timeout=3).close();checks['network']=False
except OSError:checks['network']=True
pathlib.Path('child-inside.txt').write_text('ok')
print(json.dumps(checks))
"""
child=subprocess.run([sys.executable,'-I','-B','-c',child_code,str(outside),sys.argv[2]],capture_output=True,text=True,timeout=15)
child_checks=json.loads(child.stdout) if child.returncode==0 else {}
checks['child']=set(child_checks)=={'read','write','network'} and all(child_checks.values())
print(json.dumps(checks))
'''
        probe = probe_root / "probe.py"
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        # Prove the controlled endpoint works on the host before checking denial.
        baseline = socket.create_connection(("127.0.0.1", port), timeout=2)
        accepted, _ = listener.accept()
        accepted.close()
        baseline.close()
        probe.write_text(source, encoding="utf-8")
        try:
            result = self.execute([self.config["python"], "-I", "-B", str(probe), str(outside), str(port)], probe_root, 45, cancelled)
            checks = json.loads(result["stdout"].strip())
            if result["exitCode"] != 0 or set(checks) != {"read", "write", "network", "loopback", "child", "inside"} or not all(v is True for v in checks.values()):
                raise StoreError("本机隔离探针未通过，自动运行已阻止")
            return checks
        except (ValueError, KeyError) as error:
            raise StoreError("本机隔离探针未返回完整证据，自动运行已阻止") from error
        finally:
            listener.close()
            # Only this fresh, bounded fixture; never traverse the user's trial.
            for path in (probe, probe_root / "inside.txt", probe_root / "child-inside.txt", outside):
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            if not any(probe_root.iterdir()):
                probe_root.rmdir()
            if not any(probe_parent.iterdir()):
                probe_parent.rmdir()

    def run(self, arguments, root, seconds, cancelled, *, before_execute=None):
        with tempfile.TemporaryDirectory(prefix="protocol-", dir=root.parent) as temporary:
            self.verify_protocol(Path(temporary))
        evidence = self.probe(root, cancelled)
        if before_execute:
            before_execute()
        if cancelled.is_set():
            raise StoreError("本轮已取消，未启动脚本")
        return self.execute(arguments, root, seconds, cancelled) | {"isolation": evidence}


def run_approved(service, config, request_id, adapter=None):
    lock = ProcessLock(service.worker_lock_path(request_id))
    if not lock.acquired:
        raise StoreError("运行请求已由工作进程消费")
    try:
        return _run_approved(service, config, request_id, adapter)
    finally:
        lock.close()


def _run_approved(service, config, request_id, adapter=None):
    adapter = adapter or WindowsSandbox(config)
    cancelled = threading.Event()
    with service.store.transaction() as doc:
        receipt = doc["requests"].get(request_id)
        if not receipt or receipt["status"] != "approved":
            raise StoreError("运行请求未批准或已消费")
        receipt["status"] = "running"
        receipt["started_at"] = timestamp()
        receipt["worker_pid"] = os.getpid()
        snapshot = deepcopy(receipt)
    plan = snapshot["operations"][0]
    root = service.work_root(plan["trial_id"])
    def watch():
        reader = ExperimentService(TrialStore(service.store.path), service.root)
        while not cancelled.wait(.2):
            try:
                if reader.status(request_id).get("cancel_requested"):
                    cancelled.set()
            except StoreError:
                cancelled.set()
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    result = {}
    state, error = "failed", ""
    try:
        service.reload()
        trial = service.store._find(service.snapshot(), plan["trial_id"])
        base = snapshot["base"][plan["trial_id"]]
        if trial["revision"] != base["revision"] or manifest(root) != base["files"]:
            raise StoreError("内容或文件已变化，请重新审批")
        root.mkdir(parents=True, exist_ok=True)
        # Check capabilities before materializing approved changes.
        if isinstance(adapter, WindowsSandbox):
            with tempfile.TemporaryDirectory(prefix="protocol-", dir=root.parent) as temporary:
                adapter.verify_protocol(Path(temporary))
        for file in plan["files"]:
            path = confined(root, file["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file["content"], encoding="utf-8-sig" if path.suffix.lower() == ".ps1" else "utf-8")
        prepared_files = manifest(root)
        def check_current():
            service.reload()
            current = service.store._find(service.snapshot(), plan["trial_id"])
            if current["revision"] != base["revision"] or manifest(root) != prepared_files:
                raise StoreError("隔离验证期间内容或文件发生变化，请重新审批")
        options = {"before_execute": check_current} if isinstance(adapter, WindowsSandbox) else {}
        result = adapter.run(command(config, plan), root, plan["timeout_seconds"], cancelled, **options)
        state = "cancelled" if cancelled.is_set() else "finished"
        if result.get("exitCode") == 124:
            state, error = "failed", "本轮达到执行时限；未自动重试"
            result["interruption"] = "timeout"
        elif cancelled.is_set():
            result["interruption"] = "cancelled"
    except Exception as failure:
        error = str(failure) if isinstance(failure, StoreError) else "沙箱执行失败或超时；未自动重试"
        state = "cancelled" if cancelled.is_set() else "failed"
    finally:
        cancelled.set()
        watcher.join(2)
    with service.store.transaction() as doc:
        receipt = doc["requests"][request_id]
        receipt.update(status=state, ended_at=timestamp(), error=error,
                       execution={key: result[key][:100_000] if isinstance(result[key], str) else result[key]
                                  for key in ("stdout", "stderr", "exitCode", "isolation", "interruption") if key in result})
        trial = service.store._find(doc, plan["trial_id"])
        trial["records"].append(dict(at=timestamp(), origin="runner", kind="execution", request_id=request_id,
                                     result="程序实际结果：" + REQUEST_LABELS[state] + (" · " + error if error else ""),
                                     next_action=trial["next_action"], paths=[], execution=receipt["execution"]))
        trial.update(revision=trial["revision"] + 1, updated_at=timestamp())
    return receipt


def launch_worker(config_path, request_id):
    script = Path(__file__).resolve().parents[3] / "scripts" / "run_experiment.py"
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    subprocess.Popen([config["pythonw"], "-B", str(script), str(config_path), request_id],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    parser = argparse.ArgumentParser(description="Internal approved trial worker")
    parser.add_argument("config", type=Path)
    parser.add_argument("request_id")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    root = Path(config["data_root"])
    try:
        run_approved(ExperimentService(TrialStore(root / "trials.json"), root), config, args.request_id)
    except StoreError:
        return 2
    return 0
