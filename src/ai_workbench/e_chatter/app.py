"""Qt desktop host with a small private WebChannel command surface."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, Signal, Slot, QUrl, QTimer, QLibraryInfo
from PySide6.QtGui import QDesktopServices, QCloseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from . import VERSION
from .providers import Providers
from .files import ChatterError, inside, texts
from .service import Service
from . import migration


def default_root():
    # This host opts into its approved storage path via --data; portable users
    # get an installation-local library independent of executable location.
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "ai-workbench" / "e-chatter"


class Bridge(QObject):
    result = Signal(str)
    event = Signal(str)
    open_url = Signal(str)

    def __init__(self, service, provider=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.provider = Providers(service, {"codex": lambda: provider} if provider else None)
        self.jobs = {}
        self.admission = threading.RLock()
        self.threads = []
        self.closed = False
        self.opened_auth = set()
        self.open_url.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))

    def _emit(self, value):
        if not self.closed:
            self.event.emit(json.dumps(value, ensure_ascii=False))

    def _snapshot(self):
        self._emit({"type": "snapshot", "snapshot": self.service.snapshot()})

    def _account(self, agent=None):
        value = self.provider.account(agent)
        attempt = value.get("attempt")
        if attempt:
            with self.admission:
                identity = (value["agent"], attempt["id"])
                if attempt.get("phase") == "waiting-browser" and attempt.get("authorizeUrl") and identity not in self.opened_auth:
                    self.opened_auth.add(identity)
                    self.open_url.emit(attempt["authorizeUrl"])
            # Authorization URLs are only handed to the system browser, not UI snapshots.
            value["attempt"] = {k: attempt[k] for k in ("id", "phase") if k in attempt}
        return value

    def _watch_login(self, agent):
        def watch():
            import time
            deadline = time.monotonic() + 610
            while not self.closed and time.monotonic() < deadline:
                time.sleep(.5)
                try:
                    value = self._account(agent)
                    phase = (value.get("attempt") or {}).get("phase")
                    if phase not in ("initializing", "waiting-browser", "exchanging", "committing"):
                        return
                except ChatterError:
                    return
        thread = threading.Thread(target=watch, daemon=True)
        self.threads.append(thread)
        thread.start()

    def _send(self, args):
        with self.admission:
            return self._admit(args)

    def _admit(self, args):
        session = self.service.store.get("sessions", args["session_id"])
        agent = self.service.store.setting("agent", "codex")
        if agent not in session.get("authorized_agents", ["codex"]):
            return {"provider_confirmation_required": True, "agent": agent}
        pending = args.get("task_id") or next((t["id"] for t in reversed(self.service.store.rows("tasks")) if t["session_id"] == session["id"] and t["kind"] != "chat" and t["status"] == "needs_input"), None)
        override = self.service.store.get("tasks", pending).get("model_override") if pending else None
        execution = self.provider.bind(session["id"], pending, override)
        request = self.service.prepare_request(args["session_id"], args["text"], args.get("task_id"), args.get("material_ids", []))
        if "confirmation_required" in request:
            return request
        request.update(execution=execution, model=execution["model"])
        self.service.store.update("tasks", request["task_id"], execution=execution)
        cancelled = threading.Event()
        task_id = request["task_id"]
        self.jobs[task_id] = cancelled

        def work():
            try:
                result = self.provider.generate(request, cancelled, lambda text: self._emit({"type": "delta", "task_id": task_id, "session_id": request["session_id"], "text": text}))
                if result.get("build_intake"):
                    from . import builder
                    directory = builder.prepare(self.service, request, result["build_intake"])
                    generated = builder.run(directory, cancelled)
                    result["files"] = [{"path": name, "content": value} for name, value in texts(generated).items()]
                if not cancelled.is_set():
                    self.service.complete(request, result)
            except Exception as error:
                self.service.fail(task_id, str(error) if isinstance(error, ChatterError) else "请求失败，已有记录和副本已保留", cancelled.is_set())
            finally:
                self.jobs.pop(task_id, None)
                self._emit({"type": "done", "task_id": task_id, "session_id": request["session_id"]})
                self._snapshot()
        thread = threading.Thread(target=work, daemon=True)
        self.threads.append(thread)
        thread.start()
        return {"task_id": task_id, "snapshot": self.service.snapshot()}

    def choose(self, kind):
        if not self.service.root:
            raise ChatterError("演示模式不访问本机文件")
        if kind in ("character", "characters_root"):
            return QFileDialog.getExistingDirectory(None, "选择角色目录")
        if kind == "export":
            return QFileDialog.getSaveFileName(None, "导出迁移包", "e-Chatter-library.zip", "ZIP (*.zip)")[0]
        if kind == "import":
            return QFileDialog.getOpenFileName(None, "选择迁移包", "", "ZIP (*.zip)")[0]
        if kind == "skill":
            return QFileDialog.getOpenFileName(None, "临时引用 Skill", "", "Skill (SKILL.md)")[0]
        if kind in ("codex", "deepseek"):
            return QFileDialog.getOpenFileName(None, "选择已有 Agent 入口", "", "Agent (*.exe *.cmd *.ps1)")[0]
        return QFileDialog.getOpenFileName(None, "选择写作材料", "", "材料 (*.txt *.md *.docx *.json *.yaml *.yml)")[0]

    def execute(self, method, args):
        s = self.service
        if method in ("engineering.start", "doctor.start"):
            session = s.store.get("sessions", args["session_id"])
            agent = s.store.setting("agent", "codex")
            if agent not in session.get("authorized_agents", ["codex"]):
                return {"provider_confirmation_required": True, "agent": agent}
        if method == "snapshot":
            return s.snapshot()
        if method == "folder.save":
            s.folder(**args)
        elif method == "session.save":
            session = s.session(**args)
            return {"session_id": session["id"], "snapshot": s.snapshot()}
        elif method == "character.import":
            character = s.import_character(args["path"], args.get("category", "developing"), args.get("confirmed_character", False))
            return {"character_id": character["id"], "snapshot": s.snapshot()}
        elif method == "character.refresh":
            return s.refresh_characters()
        elif method == "character.classify":
            s.classify(args["character_id"], args["category"])
        elif method == "character.load":
            return s.load_character(**args) | {"snapshot": s.snapshot()}
        elif method == "character.view":
            return {"files": texts(s.character_files(args["character_id"], args.get("version")))}
        elif method == "settings.save":
            with self.admission:
                if any(k in args for k in ("codex_cli", "deepseek_cli", "deepseek_auth")):
                    if self.jobs or any(t["kind"] != "chat" and t["status"] == "needs_input" for t in s.store.rows("tasks")):
                        raise ChatterError("请先完成或取消正在进行的任务，再更改连接")
                    result = s.settings(**args)
                    for agent in ("codex", "deepseek"):
                        if agent + "_cli" in args or agent == "deepseek" and "deepseek_auth" in args:
                            self.provider.invalidate(agent)
                    return result
                return s.settings(**args)
        elif method == "agent.select":
            with self.admission:
                if not self.provider.account(args["agent"])["connected"]:
                    raise ChatterError("请先连接并测试该 Agent")
                s.select_agent(args["agent"])
            return {"snapshot": s.snapshot(), "account": self.provider.account()}
        elif method == "models.save":
            from .providers import selection
            selection(self.provider.account(args["agent"])["models"], args)
            s.models(**args)
        elif method == "provider.authorize":
            s.authorize_provider(args["session_id"], args["agent"])
        elif method == "engineering.prepare":
            return s.prepare_engineering(args["session_id"], args["role"])
        elif method == "engineering.start":
            task = s.start_engineering(args["session_id"], args["role"], args["token"])
            if args.get("model_override"):
                s.models(args["session_id"], s.store.setting("agent", "codex"), task_id=task["id"], **args["model_override"])
            return self._send({"session_id": args["session_id"], "task_id": task["id"], "text": args.get("text") or ("请开始创建新角色，先询问所需信息。" if args["role"] == "generator" else "请检查当前角色与已有关联记录，确认本次维护范围。"), "material_ids": args.get("material_ids", [])})
        elif method == "doctor.start":
            task = s.doctor(args["session_id"], args.get("message_id"), args.get("feedback", ""))
            if args.get("model_override"):
                s.models(args["session_id"], s.store.setting("agent", "codex"), task_id=task["id"], **args["model_override"])
            return self._send({"session_id": args["session_id"], "task_id": task["id"], "text": "请诊断选定角色回复，保存诊断，并在需要维护时提供交接。"})
        elif method == "chat.send":
            return self._send(args)
        elif method == "task.cancel":
            if args["task_id"] in self.jobs:
                self.jobs[args["task_id"]].set()
            s.cancel_task(args["task_id"])
        elif method == "proposal.accept":
            return s.accept(args["proposal_id"])
        elif method == "material.attach":
            return s.attach(args["path"], args.get("as_skill", False))
        elif method == "migration.export":
            return migration.export_package(s, args["path"])
        elif method == "migration.preview":
            return migration.preview_package(s, args["path"])
        elif method == "migration.import":
            return migration.import_package(s, args["token"])
        elif method == "account.status":
            return self._account(args.get("agent"))
        elif method in ("account.login", "account.auth"):
            if not s.root:
                raise ChatterError("演示模式不操作账号或凭据")
            with self.admission:
                if self.jobs:
                    raise ChatterError("请先停止生成，再更改认证")
                result = self.provider.authenticate(args.get("agent", s.store.setting("agent", "codex")), args.get("action", "login"), **{k: v for k, v in args.items() if k not in ("agent", "action")})
            if result.get("url") and args.get("agent", s.store.setting("agent", "codex")) != "deepseek":
                self.open_url.emit(result["url"])
            if result.get("pending") and args.get("action", "login") == "login" and args.get("agent", s.store.setting("agent", "codex")) == "deepseek":
                self._watch_login("deepseek")
            return {k: v for k, v in result.items() if k != "url"}
        elif method == "directory.open":
            if not s.root:
                raise ChatterError("演示模式不打开本机目录")
            self.open_url.emit(QUrl.fromLocalFile(s.store.setting("characters_root")).toString())
            return {"opened": True}
        else:
            raise ChatterError("应用不提供此操作")
        return s.snapshot()

    @Slot(str)
    def dispatch(self, encoded):
        try:
            request = json.loads(encoded)
            if set(request) != {"id", "method", "args"} or not isinstance(request["args"], dict):
                raise ChatterError("无效的应用请求")
            if request["method"] == "path.choose":
                value = self.choose(request["args"]["kind"])
                self.result.emit(json.dumps({"id": request["id"], "result": value}, ensure_ascii=False))
                return
        except Exception:
            self.result.emit(json.dumps({"id": None, "error": "无效的应用请求"}))
            return

        def work():
            try:
                value = self.execute(request["method"], request["args"])
                result = {"id": request["id"], "result": value}
            except Exception as error:
                result = {"id": request["id"], "error": str(error) if isinstance(error, ChatterError) else "操作失败，已有资料未被覆盖"}
            if not self.closed:
                self.result.emit(json.dumps(result, ensure_ascii=False))
        thread = threading.Thread(target=work, daemon=True)
        self.threads.append(thread)
        thread.start()

    def close(self):
        self.closed = True
        for task_id, cancelled in list(self.jobs.items()):
            cancelled.set()
            self.service.cancel_task(task_id)
        self.provider.close()
        for thread in self.threads:
            thread.join(timeout=2)


class Page(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if url.scheme() == "file":
            return Path(url.toLocalFile()).resolve() == (Path(__file__).with_name("web") / "index.html").resolve()
        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if url.scheme() in ("http", "https", "mailto"):
                QDesktopServices.openUrl(url)
            return False
        if url.scheme() in ("qrc", "about"):
            return True
        return False


class Window(QMainWindow):
    def __init__(self, service, provider=None, url=None):
        super().__init__()
        self.setWindowTitle(f"e-Chatter {VERSION}")
        self.resize(1440, 960)
        self.setMinimumSize(900, 640)
        self.view = QWebEngineView(self)
        self.profile = QWebEngineProfile(self)  # off-the-record web profile; data belongs to Python
        self.page = Page(self.profile, self)
        self.view.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.channel = QWebChannel(self.page)
        self.bridge = Bridge(service, provider, self)
        self.channel.registerObject("chatter", self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        html = Path(__file__).with_name("web") / "index.html"
        if not html.exists() and not url:
            raise ChatterError("缺少前端构建产物，请运行 e-Chatter 前端 build 或使用完整便携包")
        self.view.setUrl(QUrl(url) if url else QUrl.fromLocalFile(str(html.resolve())))

    def closeEvent(self, event: QCloseEvent):
        self.bridge.close()
        event.accept()


def create_application():
    # Importing this module initializes QtWebEngine before QApplication exists.
    platforms = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "platforms"
    return QApplication.instance() or QApplication(["e-Chatter", "-platformpluginpath", str(platforms)])


def main(argv=None):
    parser = argparse.ArgumentParser(description="e-Chatter local desktop character platform")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--data", type=Path)
    parser.add_argument("--role-worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-exit-ms", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.role_worker:
        from .builder import worker
        worker(args.role_worker)
        return 0
    app = create_application()
    app.setApplicationName("e-Chatter")
    app.setApplicationVersion(VERSION)
    service = Service(None if args.demo else (args.data or default_root()))
    if args.demo:
        service.seed_demo()
    window = Window(service)
    window.show()
    if args.smoke_exit_ms:
        QTimer.singleShot(args.smoke_exit_ms, window.close)
    return app.exec()
