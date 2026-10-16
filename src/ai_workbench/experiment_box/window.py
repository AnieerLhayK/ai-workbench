"""Native window composition; persistence and dispatch live behind Modules."""
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QSize, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QLineEdit, QComboBox, QListWidget, QListWidgetItem,
                              QScrollArea, QFrame, QFormLayout, QPlainTextEdit, QDialog, QMessageBox)

from .dialogs import TrialDialog, ResultDialog, ConfirmDialog, text_label
from .launch import command_request
from .model import STATUSES, StoreError, FIELD_LABELS
from .style import STYLE
from .icons import icon
from .service import ExperimentService
from .assistant import AssistantJobs, CodexAssistant
from .assistant_ui import AssistantPanel, ApprovalDialog


def button(text, action, *, primary=False):
    result = QPushButton(text)
    if primary:
        result.setObjectName("primary")
    result.clicked.connect(action)
    return result


def panel(title):
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(28, 24, 28, 26)
    layout.setSpacing(18)
    layout.addWidget(text_label(title, "sectionHeading"))
    return frame, layout


class ExperimentWindow(QMainWindow):
    auth_result = Signal(str)
    def __init__(self, store, launcher, *, demo=False, confirm=ConfirmDialog, config=None, config_path=None, assistant_adapter=None):
        super().__init__()
        store = store if isinstance(store, ExperimentService) else ExperimentService(store)
        self.store, self.launcher, self.demo, self.confirm = store, launcher, demo, confirm
        self.config, self.config_path = config or {}, config_path
        self.closed = False
        self.jobs = AssistantJobs(store, assistant_adapter or (CodexAssistant(self.config) if self.config.get("codex_cli") and not demo else None), self)
        self.current_id = store.snapshot()["selected_id"]
        self.setWindowTitle("个人试验盒")
        self.resize(1440, 1000)
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header.setObjectName("header")
        top = QHBoxLayout(header)
        top.setContentsMargins(26, 10, 24, 10)
        mark = QLabel()
        mark.setPixmap(QIcon(str(Path(__file__).resolve().parents[1] / "assets" / "experiment-box.svg")).pixmap(26, 26))
        top.addWidget(mark)
        top.addWidget(text_label("个人试验盒", "brand"))
        if demo:
            top.addWidget(text_label("演示数据", "muted"))
        top.addStretch()
        self.create_button = button("手动新建", self.new_trial)
        top.addWidget(self.create_button)
        self.assistant_toggle = button("助手", self.toggle_assistant)
        top.addWidget(self.assistant_toggle)
        outer.addWidget(header)
        body = QHBoxLayout()
        self.body = body
        body.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(285)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(0, 22, 0, 0)
        self.overview_button = button("⌂  总览", self.show_overview)
        self.overview_button.setCheckable(True)
        left.addWidget(self.overview_button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称或标签")
        self.search.setAccessibleName("搜索名称或标签")
        self.search.addAction(icon("search", "#a7afbb"), QLineEdit.ActionPosition.LeadingPosition)
        self.filter = QComboBox()
        self.filter.addItems(["全部", *STATUSES])
        self.filter.setAccessibleName("筛选试验状态")
        controls = QVBoxLayout()
        controls.setContentsMargins(22, 0, 22, 14)
        controls.setSpacing(12)
        controls.addWidget(self.search)
        controls.addWidget(self.filter)
        left.addLayout(controls)
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setAccessibleName("试验列表")
        left.addWidget(self.list)
        self.list_empty = text_label("", "muted")
        self.list_empty.setContentsMargins(24, 12, 24, 24)
        left.addWidget(self.list_empty)
        body.addWidget(sidebar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        detail = QWidget()
        right = QVBoxLayout(detail)
        right.setContentsMargins(24, 24, 24, 22)
        right.setSpacing(20)
        heading_row = QHBoxLayout()
        self.heading = text_label("创建你的第一项试验", "heading")
        heading_row.addWidget(self.heading, 1)
        self.edit_button = button("编辑", self.edit_trial)
        self.source_button = button("打开来源", self.open_source)
        self.edit_button.setIcon(icon("edit"))
        self.source_button.setIcon(icon("source"))
        heading_row.addWidget(self.edit_button)
        heading_row.addWidget(self.source_button)
        right.addLayout(heading_row)
        self.updated = text_label("", "muted")
        right.addWidget(self.updated)
        goal_frame = QFrame()
        goal_layout = QHBoxLayout(goal_frame)
        goal_layout.setContentsMargins(0, 8, 0, 14)
        goal_layout.setSpacing(22)
        self.goal_frame = goal_frame
        self.next_action = text_label("")
        self.next_action.setAccessibleName("下一步")
        self.goal, self.source, self.tags = (text_label("") for _ in range(3))
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source.setStyleSheet("color: #61b9d0;")
        self.space = text_label("")
        for title, field, stretch in (("目标", self.goal, 2), ("下一步", self.next_action, 2), ("标签", self.tags, 1), ("试验空间", self.space, 1)):
            column = QVBoxLayout()
            column.setSpacing(10)
            column.addWidget(text_label(title, "muted"))
            column.addWidget(field)
            column.addStretch()
            goal_layout.addLayout(column, stretch)
        right.addWidget(goal_frame)
        self.approvals_frame, self.approvals_layout = panel("待你确认")
        right.addWidget(self.approvals_frame)
        self.manual_toggle = button("人工终端与启动配置 ▸", lambda: config_frame.setVisible(not config_frame.isVisible()))
        right.addWidget(self.manual_toggle)
        config_frame, config_layout = panel("启动配置")
        config_form = QFormLayout()
        config_form.setHorizontalSpacing(18)
        config_form.setVerticalSpacing(14)
        self.directory = QLineEdit()
        self.directory.setReadOnly(True)
        self.directory.setAccessibleName("工作目录")
        folder = self.directory.addAction(icon("folder"), QLineEdit.ActionPosition.TrailingPosition)
        folder.triggered.connect(self.edit_trial)
        self.command = QPlainTextEdit()
        self.command.setReadOnly(True)
        self.command.setFixedHeight(76)
        self.command.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.command.setAccessibleName("PowerShell 命令")
        config_form.addRow("工作目录", self.directory)
        config_form.addRow("PowerShell 命令", self.command)
        config_layout.addLayout(config_form)
        actions = QHBoxLayout()
        self.launch_button = button("打开人工终端", self.start_trial)
        self.record_button = button("记录结果", self.record_result)
        self.launch_button.setIcon(icon("play", "#10212a"))
        self.record_button.setIcon(icon("record"))
        actions.addWidget(self.launch_button)
        actions.addWidget(self.record_button)
        actions.addWidget(text_label("启动前确认目录与命令", "muted"), 1)
        config_layout.addLayout(actions)
        self.dispatch_hint = text_label("", "hint")
        self.dispatch_hint.hide()
        config_layout.addWidget(self.dispatch_hint)
        right.addWidget(config_frame)
        self.config_frame = config_frame
        config_frame.hide()
        self.records_frame, self.records_layout = panel("试验记录")
        self.records_frame.setObjectName("history")
        self.records_layout.setContentsMargins(0, 10, 0, 10)
        self.records_frame.setMinimumHeight(170)
        right.addWidget(self.records_frame)
        self.error = text_label("", "error")
        right.addWidget(self.error)
        right.addStretch()
        scroll.setWidget(detail)
        right_column = QWidget()
        right_column_layout = QVBoxLayout(right_column)
        right_column_layout.setContentsMargins(0, 0, 0, 0)
        right_column_layout.addWidget(scroll, 1)
        footer = text_label("普通更新自动保存 · 关键操作由你确认", "muted")
        footer.setContentsMargins(28, 8, 26, 18)
        right_column_layout.addWidget(footer)
        body.addWidget(right_column, 1)
        self.assistant_panel = AssistantPanel()
        self.assistant_panel.setFixedWidth(385)
        body.addWidget(self.assistant_panel)
        self.assistant_panel.send.connect(self.send_prompt)
        self.assistant_panel.cancel.connect(self.jobs.cancel)
        self.assistant_panel.retry.connect(self.jobs.retry_save)
        self.jobs.changed.connect(self.assistant_changed)
        self.auth_result.connect(self.assistant_panel.auth.setText)
        outer.addLayout(body, 1)
        self.search.textChanged.connect(self.refresh_list)
        self.filter.currentTextChanged.connect(self.refresh_list)
        self.list.currentItemChanged.connect(self.select_trial)
        self.stop_observing = self.launcher.observe(self.dispatch_changed)
        self.refresh_list()
        self._revision = self.store.snapshot().get("revision", 0)
        self.poll = QTimer(self)
        self.poll.setInterval(750)
        self.poll.timeout.connect(self.refresh_external)
        self.poll.start()
        if demo:
            self.assistant_panel.auth.setText("演示 · 不连接账号")
        elif self.config.get("codex_cli"):
            import threading
            threading.Thread(target=self.check_auth, daemon=True).start()
        else:
            self.assistant_panel.auth.setText("未配置 Codex")

    def trial(self):
        trial_id = getattr(self, "displayed_id", self.current_id)
        return next((t for t in self.store.snapshot()["trials"] if t["id"] == trial_id), None)

    def refresh_list(self):
        visible = self.store.trials(self.search.text(), self.filter.currentText())
        self.displayed_id = self.current_id if any(t["id"] == self.current_id for t in visible) else None
        self.list.blockSignals(True)
        self.list.clear()
        for trial in visible:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, trial["id"])
            self.list.addItem(item)
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            content = QVBoxLayout(row)
            content.setContentsMargins(24, 16, 24, 16)
            content.setSpacing(8)
            title = QHBoxLayout()
            name = text_label(trial["name"])
            name.setStyleSheet("font-weight: 600;")
            title.addWidget(name, 1)
            state = text_label(trial["status"], "muted")
            state.setStyleSheet("color: " + {"试验中": "#61b9d0", "暂停": "#d4b567", "已完成": "#8ec6a3"}.get(trial["status"], "#a7afbb") + ";")
            title.addWidget(state)
            content.addLayout(title)
            content.addWidget(text_label(trial["next_action"] or "填写下一步", "muted"))
            content.addWidget(text_label(" · ".join(trial["tags"]), "muted"))
            row.ensurePolished()
            item.setSizeHint(QSize(260, max(132, content.totalHeightForWidth(260))))
            self.list.setItemWidget(item, row)
            if trial["id"] == self.current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.overview_button.setChecked(self.current_id is None)
        if self.current_id is None:
            self.list.clearSelection()
        self.list_empty.setText("" if visible else "尚无试验。可在总览助手输入 @新建试验，或点击手动新建。" if not self.store.snapshot()["trials"] else "没有匹配的试验")
        self.show_trial()

    def select_trial(self, item, previous=None):
        if item is None:
            return
        selected = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.store.select(selected)
        except StoreError as error:
            self.error.setText(str(error))
            self.refresh_list()
            return
        self.current_id = selected
        self.displayed_id = selected
        self.error.clear()
        self.show_trial()

    def show_trial(self):
        trial = self.trial()
        self.heading.setText(trial["name"] if trial else "试验总览" if self.current_id is None else "没有匹配的试验")
        self.next_action.setText(trial["next_action"] if trial else "点击右上角新建试验")
        self.goal.setText(trial["goal"] if trial else "记录想尝试的工具、目标与下一步")
        self.goal_frame.setVisible(trial is not None)
        self.updated.setText("最近更新 · " + datetime.fromisoformat(trial["updated_at"]).astimezone().strftime("%Y-%m-%d %H:%M") if trial else "查看待确认操作与最近更新；在总览助手中创建新试验。")
        self.space.setText(trial["id"][:8] if trial else "")
        self.source.setText(trial["source"] if trial else "")
        self.tags.setText(" · ".join(trial["tags"]) if trial else "")
        self.directory.setText(trial["directory"] if trial else "")
        self.command.setPlainText(trial["command"] if trial else "")
        self.edit_button.setEnabled(trial is not None)
        self.edit_button.setVisible(trial is not None)
        self.source_button.setEnabled(bool(trial and trial["source"]))
        self.source_button.setVisible(bool(trial and trial["source"]))
        self.record_button.setEnabled(trial is not None)
        self.launch_button.setEnabled(trial is not None and not self.launcher.state.pending)
        self.manual_toggle.setVisible(trial is not None)
        if trial is None:
            self.config_frame.hide()
        self.render_approvals()
        context = self.current_id or "overview"
        self.assistant_panel.render(context, self.store.snapshot().get("conversations", {}).get(context, []), self.jobs.pending,
                                    self.jobs.adapter is not None and (trial is not None or self.current_id is None))
        self.assistant_panel.retry_button.setVisible(self.jobs.failed_result)
        while self.records_layout.count() > 1:
            item = self.records_layout.takeAt(1)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        records = trial["records"] if trial else sorted([r | {"trial_name": t["name"]} for t in self.store.trials() for r in t["records"]], key=lambda r: r["at"])[-30:]
        self.records_layout.itemAt(0).widget().setText("历史记录" if trial else "最近更新")
        if not records:
            empty = text_label("尚无记录", "muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(100)
            self.records_layout.addWidget(empty)
        for record in reversed(records):
            when = datetime.fromisoformat(record["at"]).astimezone().strftime("%Y-%m-%d %H:%M")
            origin = {"human": "人工", "cli": "CLI", "assistant": "Codex", "runner": "程序实际执行"}.get(record.get("origin"), "人工（旧记录）")
            text = when + " · " + origin + (" · " + record["trial_name"] if "trial_name" in record else "") + "\n" + record["result"] + "\n下一步：" + record["next_action"]
            if record["paths"]:
                text += "\n文件路径：\n" + "\n".join(record["paths"])
            if "execution" in record:
                evidence = record["execution"]
                text += "\n退出码：" + str(evidence.get("exitCode", "未执行")) + "\n" + evidence.get("stdout", "") + evidence.get("stderr", "")
            self.records_layout.addWidget(text_label(text))

    def show_overview(self):
        try:
            self.store.select(None)
            self.current_id = None
            self.refresh_list()
        except StoreError as error:
            self.error.setText(str(error))

    def render_approvals(self):
        while self.approvals_layout.count() > 1:
            item = self.approvals_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        receipts = [r for r in self.store.snapshot().get("requests", {}).values()
                    if r["status"] in ("pending", "approved", "running") and (self.current_id is None or any(o.get("trial_id") == self.current_id for o in r["operations"]))]
        for receipt in receipts:
            is_plan = receipt["operations"][0]["action"] == "plan"
            title = ("本轮试验计划" if is_plan else "试验内容变更") + " · " + {"pending": "等待你批准", "approved": "等待运行", "running": "运行中"}[receipt["status"]]
            self.approvals_layout.addWidget(text_label(title, "sectionHeading"))
            for op in receipt["operations"]:
                trial = next((t for t in self.store.trials() if t["id"] == op.get("trial_id")), {})
                if self.current_id is None:
                    self.approvals_layout.addWidget(text_label(trial.get("name", op.get("fields", {}).get("name", "新建试验"))))
                if op["action"] == "plan":
                    self.approvals_layout.addWidget(text_label(op["goal"], "muted"))
                    if self.current_id:
                        self.approvals_layout.addWidget(text_label("① 准备验证文件\n" + ("\n".join(f["path"] for f in op["files"]) or "使用本试验已有文件")))
                        self.approvals_layout.addWidget(text_label("② 运行离线脚本\n" + op["runtime"] + " " + op["script"] + " · 最多 " + str(op["timeout_seconds"]) + " 秒"))
                        self.approvals_layout.addWidget(text_label("③ 保存结果与下一步\n程序记录输出与退出码，试验是否完成由你决定。", "muted"))
                elif op["action"] in ("create", "update"):
                    for key, value in op["fields"].items():
                        self.approvals_layout.addWidget(text_label(FIELD_LABELS[key] + "：" + str(value), "muted"))
            if receipt["status"] == "pending":
                row = QWidget()
                actions = QHBoxLayout(row)
                actions.setContentsMargins(0, 6, 0, 0)
                actions.addStretch()
                review = button("查看并批准" if is_plan else "查看变更", lambda checked=False, r=receipt: self.review(r), primary=True)
                actions.addWidget(review)
                reject = button("退回修改", lambda checked=False, r=receipt: self.reject_proposal(r))
                actions.addWidget(reject)
                self.approvals_layout.addWidget(row)
            elif receipt["status"] == "running":
                self.approvals_layout.addWidget(button("取消本轮运行", lambda checked=False, r=receipt: self.cancel_run(r["request_id"])))
        if not receipts:
            self.approvals_layout.addWidget(text_label("暂无待确认操作。普通更新会自动保存，目标调整、完成和试验计划由你决定。", "muted"))

    def review(self, receipt):
        try:
            self.store.reload()
            current = self.store.status(receipt["request_id"])
            if self.demo:
                raise StoreError("演示模式不会批准或执行本机操作")
            dialog = ApprovalDialog(current, self.store, self.config, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                if dialog.reject_request:
                    self.reject_proposal(current)
                return
            decided = self.store.decide(current["request_id"], current["plan_hash"], approve=True)
            if decided["status"] == "approved":
                try:
                    if not self.config_path:
                        raise StoreError("没有本机工作进程配置，未启动试验")
                    from .runner import launch_worker
                    launch_worker(self.config_path, decided["request_id"])
                except (StoreError, OSError):
                    self.store.fail_launch(decided["request_id"])
                    raise
            self.refresh_list()
            if decided["status"] == "conflict":
                self.error.setText(decided["error"])
        except (StoreError, OSError) as error:
            self.error.setText(str(error))

    def reject_proposal(self, receipt):
        try:
            self.store.decide(receipt["request_id"], receipt["plan_hash"], approve=False)
            self.refresh_list()
        except StoreError as error:
            self.error.setText(str(error))

    def cancel_run(self, request_id):
        try:
            self.store.cancel_execution(request_id)
        except StoreError as error:
            self.error.setText(str(error))

    def send_prompt(self, text, materials):
        try:
            if self.jobs.send(self.current_id or "overview", text, materials):
                self.assistant_panel.accepted()
                self.show_trial()
        except StoreError as error:
            self.error.setText(str(error))

    def assistant_changed(self, context):
        if context.startswith("保存失败"):
            self.error.setText(context)
        self.refresh_list()

    def refresh_external(self):
        try:
            self.store.reload()
            revision = self.store.snapshot().get("revision", 0)
            if revision != self._revision:
                self._revision = revision
                self.refresh_list()
        except StoreError as error:
            self.error.setText(str(error))

    def check_auth(self):
        import subprocess
        from ..e_diary.codex import argv
        try:
            result = subprocess.run(argv(self.config["codex_cli"], "login", "status"), capture_output=True, timeout=15,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            if not self.closed:
                self.auth_result.emit("已登录" if result.returncode == 0 and "Logged in" in text else "未登录")
        except (OSError, subprocess.TimeoutExpired):
            if not self.closed:
                self.auth_result.emit("登录状态不可用")

    def toggle_assistant(self):
        if self.width() < 1280:
            if not hasattr(self, "assistant_drawer"):
                self.assistant_drawer = QDialog(self)
                self.assistant_drawer.setWindowTitle("试验助手")
                layout = QVBoxLayout(self.assistant_drawer)
                layout.setContentsMargins(0, 0, 0, 0)
            self.assistant_drawer.layout().addWidget(self.assistant_panel)
            self.assistant_panel.setFixedWidth(400)
            self.assistant_panel.show()
            self.assistant_drawer.resize(400, min(700, self.height() - 40))
            self.assistant_drawer.show()
            self.assistant_panel.composer.setFocus()
        else:
            self.assistant_panel.setVisible(not self.assistant_panel.isVisible())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "assistant_panel"):
            if self.width() >= 1280 and hasattr(self, "assistant_drawer") and self.assistant_panel.parent() == self.assistant_drawer:
                self.body.addWidget(self.assistant_panel)
                self.assistant_panel.setFixedWidth(385)
                self.assistant_drawer.hide()
            self.assistant_panel.setVisible(self.width() >= 1280)

    def closeEvent(self, event):
        try:
            self.jobs.close()
        except StoreError as error:
            QMessageBox.warning(self, "结果尚未保存", str(error))
            event.ignore()
            return
        self.closed = True
        self.poll.stop()
        self.assistant_panel.composer.removeEventFilter(self.assistant_panel)
        if self.stop_observing:
            self.stop_observing()
            self.stop_observing = None
        self.manual_toggle.clicked.disconnect()
        super().closeEvent(event)

    def new_trial(self):
        self.edit_dialog(None)

    def edit_trial(self):
        self.edit_dialog(self.trial())

    def edit_dialog(self, trial):
        dialog = TrialDialog(self.store, trial, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_id = dialog.saved_id
            self.error.clear()
            self.refresh_list()

    def record_result(self):
        trial = self.trial()
        if trial and ResultDialog(self.store, trial, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh_list()

    def open_source(self):
        trial = self.trial()
        if trial and trial["source"] and not QDesktopServices.openUrl(QUrl(trial["source"])):
            self.error.setText("系统浏览器未能打开来源链接")

    def start_trial(self):
        if self.launcher.state.pending:
            return
        trial = self.trial()
        if not trial:
            return
        try:
            request = command_request(trial)
        except ValueError as error:
            self.error.setText(str(error))
            return
        if self.confirm(request, self).exec() == QDialog.DialogCode.Accepted:
            self.error.clear()
            self.launcher.launch(request)

    def dispatch_changed(self, state):
        self.launch_button.setEnabled(self.trial() is not None and not state.pending)
        message = "正在打开终端…" if state.pending else state.error or ("终端已打开，请在终端完成试验" if state.dispatched else "")
        self.dispatch_hint.setText(message)
        self.dispatch_hint.setVisible(bool(message))
