"""Native CI panel: automatic discovery, explicit repair, local patch review."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget


STATUS = {"detected": "待开始", "running": "修复中", "patch_ready": "补丁待审", "needs_review": "需人工复核", "failed": "未完成", "interrupted": "已中断", "superseded": "PR 已变化", "cleared": "当前无失败"}


def parse_test_command(value):
    if os.name != "nt":
        return shlex.split(value)
    import ctypes
    from ctypes import wintypes
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    args = shell.CommandLineToArgvW("ci-command " + value, ctypes.byref(count))
    if not args:
        raise ValueError("Invalid command line")
    try:
        return [args[index] for index in range(1, count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(args, wintypes.HLOCAL))


class DemoCIClient:
    def __init__(self):
        self.value = {"settings": {"agent": "dsh", "model": "", "enabled": False, "repositories": [{"slug": "demo/example", "path": "demo/ci-project"}], "test_command": ["python", "-m", "pytest"]}, "jobs": [{"id": "demo", "repository": {"slug": "demo/example"}, "number": 17, "checks": ["unit-tests"], "status": "detected", "head": "a" * 40}]}

    def snapshot(self):
        return deepcopy(self.value)

    def status(self):
        return {"heartbeat": time.time(), "monitoring": self.value["settings"]["enabled"]}

    def send(self, action, **values):
        if action in ("configure", "configure_and_scan", "configure_and_repair"):
            self.value["settings"].update(values["values"])
        if action in ("repair", "configure_and_repair"):
            self.value["jobs"][0]["status"] = "running"
            QTimer.singleShot(400, lambda: self.value["jobs"][0].update(status="patch_ready"))


class CIWindow(QDialog):
    def __init__(self, client, parent=None, project="", demo=False):
        super().__init__(parent)
        self.client, self.demo, self.jobs = client, demo, []
        self.setWindowTitle("muti-ai · CI 修复")
        self.resize(900, 640)
        self.setMinimumSize(700, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("CI 修复")
        title.setStyleSheet("font-size:22px;font-weight:600")
        layout.addWidget(title)
        layout.addWidget(QLabel("自动发现 GitHub Actions 失败，手动开始修复。结果保留为本地补丁。"))
        self.notice = QLabel("模拟演示 · 不访问真实仓库或调用模型" if demo else "关闭窗口后，已开启的监测和修复继续运行。")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        settings = client.snapshot().get("settings", {})
        repositories = settings.get("repositories", [])
        repository = repositories[0] if repositories else {}
        form = QFormLayout()
        self.repository = QLineEdit(repository.get("slug", ""))
        self.repository.setPlaceholderText("owner/repository")
        self.repository.setAccessibleName("GitHub 仓库")
        form.addRow("GitHub 仓库", self.repository)
        path_line = QHBoxLayout()
        self.directory = QLineEdit(repository.get("path", project))
        self.directory.setAccessibleName("本地仓库根目录")
        path_line.addWidget(self.directory, 1)
        self.browse = QPushButton("选择目录")
        self.browse.setEnabled(not demo)
        self.browse.clicked.connect(self.choose_directory)
        path_line.addWidget(self.browse)
        form.addRow("本地仓库", path_line)
        agent_line = QHBoxLayout()
        self.agent = QComboBox()
        self.agent.setEditable(True)
        self.agent.addItems(["dsh", "claude", "codex"])
        self.agent.setCurrentText(settings.get("agent", "dsh"))
        self.agent.setAccessibleName("修复 agent")
        self.model = QLineEdit(settings.get("model", ""))
        self.model.setPlaceholderText("留空沿用该 agent 的原生默认模型")
        self.model.setAccessibleName("修复 model")
        self.model_values = dict(settings.get("models", {}))
        self.previous_agent = self.agent.currentText()
        self.model_values[self.previous_agent] = self.model.text()
        self.agent.currentTextChanged.connect(self.change_agent)
        agent_line.addWidget(self.agent)
        agent_line.addWidget(self.model, 1)
        form.addRow("Agent / model", agent_line)
        self.tests = QLineEdit((subprocess.list2cmdline if os.name == "nt" else shlex.join)(settings.get("test_command", ["python", "-m", "pytest"])))
        self.tests.setAccessibleName("修复验证命令")
        form.addRow("验证命令", self.tests)
        layout.addLayout(form)
        self.more = QToolButton()
        self.more.setText("更多执行设置")
        self.more.setCheckable(True)
        self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.more, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        advanced_form = QFormLayout(self.advanced)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        self.skill = QLineEdit(settings.get("skill_path", ""))
        self.skill.setPlaceholderText("留空使用 Codex 技能目录中的 gh-fix-ci；也可填写安装目录")
        advanced_form.addRow("修复指令目录", self.skill)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText('可选：自定义 agent 的命令 argv JSON，支持 {workspace}、{prompt_file}、{model}')
        advanced_form.addRow("自定义命令", self.custom)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        self.more.toggled.connect(self.advanced.setVisible)
        self.more.toggled.connect(lambda checked: self.more.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
        buttons = QHBoxLayout()
        self.save = QPushButton("保存设置")
        self.monitor = QPushButton()
        self.scan = QPushButton("立即扫描")
        self.repair = QPushButton("开始修复所选项")
        self.patch = QPushButton("查看补丁")
        for button in (self.save, self.monitor, self.scan, self.repair, self.patch):
            button.setObjectName("launchButton")
            buttons.addWidget(button)
        self.repair.setStyleSheet("QPushButton {background:#245b91;color:white;padding:8px 12px;border-radius:4px;} QPushButton:disabled {background:#59616d;color:#c5cbd3;}")
        self.save.clicked.connect(lambda: self.configure())
        self.monitor.clicked.connect(self.toggle_monitor)
        self.scan.clicked.connect(self.scan_now)
        self.repair.clicked.connect(self.start_repair)
        self.patch.clicked.connect(self.open_patch)
        layout.addLayout(buttons)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["仓库", "PR / 检查", "状态", "执行 agent / model"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def choose_directory(self):
        selected = QFileDialog.getExistingDirectory(self, "选择本地 Git 仓库", self.directory.text())
        if selected:
            self.directory.setText(selected)

    def change_agent(self, selected):
        self.model_values[self.previous_agent] = self.model.text()
        self.model.setText(self.model_values.get(selected, ""))
        self.previous_agent = selected

    def configure(self, enabled=None, action="configure", job_id=None):
        try:
            agent = self.agent.currentText().strip()
            command = parse_test_command(self.tests.text())
            if not command or not agent:
                raise ValueError("请配置 agent 和验证命令")
            values = {"repositories": [{"slug": self.repository.text().strip(), "path": self.directory.text().strip()}], "agent": agent, "model": self.model.text().strip(), "test_command": command, "skill_path": self.skill.text().strip()}
            self.model_values[agent] = self.model.text().strip()
            values["models"] = dict(self.model_values)
            if enabled is not None:
                values["enabled"] = enabled
            if self.custom.text().strip():
                custom = json.loads(self.custom.text())
                if not isinstance(custom, list) or not custom or any(not isinstance(value, str) for value in custom):
                    raise ValueError("自定义命令须为非空字符串列表")
                commands = self.client.snapshot().get("settings", {}).get("agent_commands", {})
                values["agent_commands"] = {**commands, agent: custom}
            request = {"values": values}
            if job_id is not None:
                request["job_id"] = job_id
            self.client.send(action, **request)
            return True
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "设置未保存", str(error))
            return False

    def toggle_monitor(self):
        self.configure(not self.client.snapshot().get("settings", {}).get("enabled", False))

    def scan_now(self):
        self.configure(action="configure_and_scan")

    def selected_job(self):
        row = self.table.currentRow()
        return self.jobs[row] if 0 <= row < len(self.jobs) else None

    def start_repair(self):
        job = self.selected_job()
        if job and self.configure(action="configure_and_repair", job_id=job["id"]):
            self.repair.setEnabled(False)

    def open_patch(self):
        job = self.selected_job()
        if job and not self.demo:
            path = self.client.root / "jobs" / job["id"] / "change.diff"
            if path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def selection_changed(self):
        job = self.selected_job()
        self.repair.setEnabled(bool(job and job["status"] in ("detected", "failed", "interrupted") and not any(item["status"] == "running" for item in self.jobs)))
        self.patch.setEnabled(bool(job and job["status"] in ("patch_ready", "needs_review", "failed") and not self.demo))

    def refresh(self):
        previous = self.selected_job()
        self.jobs = list(reversed(self.client.snapshot().get("jobs", [])))
        self.table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            execution = job.get("execution", {})
            native = (job.get("result") or {}).get("native", {})
            identity = execution.get("agent", "") + " / " + (native.get("model") or execution.get("model") or "原生默认") if execution else "开始时确定"
            values = [job["repository"]["slug"], f"#{job['number']} · " + ", ".join(job.get("checks", [])), STATUS.get(job["status"], job["status"]), identity]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            if previous and previous["id"] == job["id"]:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        status = self.client.status()
        fresh = time.time() - status.get("heartbeat", 0) < 15
        enabled = self.client.snapshot().get("settings", {}).get("enabled", False)
        self.monitor.setText("暂停监测" if enabled else "开启监测")
        detail = "后台监测中" if fresh and status.get("monitoring") else "监测已暂停" if fresh else "后台状态未确认"
        job = self.selected_job()
        problem = status.get("error") or ((job.get("result") or {}).get("error") if job else None)
        self.state_label.setText(detail + (" · " + problem if problem else ""))
        self.selection_changed()

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
