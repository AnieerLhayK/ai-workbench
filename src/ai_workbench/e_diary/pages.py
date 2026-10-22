"""Settings, registry and report UI families; no model work on the GUI thread."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QDate, Qt, QUrl, QTime, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QSpinBox, QCheckBox, QFileDialog, QTextEdit,
    QTextBrowser, QListWidget, QTabWidget, QDialog, QDialogButtonBox, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit, QSplitter, QStackedWidget, QTimeEdit, QAbstractItemView, QScrollArea)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView

from .library import DiaryError, KINDS
from .reports import NOTICE
from .settings import StyleResources
from ..app import Switch


def heading(text):
    label = QLabel(text)
    label.setObjectName("heading")
    return label


def date_input(value=None):
    widget = QDateEdit(value or QDate.currentDate())
    widget.setCalendarPopup(True)
    widget.setDisplayFormat("yyyy-MM-dd")
    return widget


def period_request(parent, kind):
    dialog = QDialog(parent)
    dialog.setWindowTitle("选择生成时期")
    layout = QFormLayout(dialog)
    end = date_input(QDate.currentDate())
    start = date_input(QDate.currentDate().addDays(-20 if kind == "personal" else -6))
    prompt = QTextEdit()
    prompt.setPlaceholderText("可补充这次总结关注的内容")
    zf = QCheckBox("启用 user-style 私有风格")
    zf.setChecked(kind == "personal")
    layout.addRow("开始日期", start)
    layout.addRow("结束日期（包含当天）", end)
    layout.addRow("补充要求", prompt)
    layout.addRow(zf)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)
    if dialog.exec() != QDialog.Accepted:
        return None
    return {"kind": kind, "start": datetime.combine(start.date().toPython(), datetime.min.time()).astimezone().isoformat(),
            "end": datetime.combine(end.date().addDays(1).toPython(), datetime.min.time()).astimezone().isoformat(),
            "prompt": prompt.toPlainText(), "zf": zf.isChecked()}


class Preferences(QWidget):
    def __init__(self, settings, config, on_theme):
        super().__init__()
        self.settings, self.config = settings, config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.addWidget(heading("设置"))
        form = QFormLayout()
        self.theme = QComboBox()
        for label, value in (("浅色", "light"), ("深色", "dark"), ("跟随系统", "system")):
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(self.theme.findData(settings.data["theme"]))
        self.theme.currentIndexChanged.connect(lambda: on_theme(self.theme.currentData()))
        form.addRow("外观", self.theme)
        self.fields = {}
        for key, label in (("codex_cli", "Codex CLI"), ("prose_path", "prose.md（留空使用内置规范）"), ("zf_root", "user-style 同步源目录"),
                           ("staging_root", "临时任务目录"), ("model", "模型（留空沿用 Codex）")):
            field = QLineEdit(str(config.get(key, "")))
            if key == "prose_path":
                field.setPlaceholderText("内置 prose.md；可填写自定义文件的绝对路径")
            self.fields[key] = field
            form.addRow(label, field)
        self.read_sessions = QCheckBox("读取本机 Codex 历史（只读，不恢复原会话）")
        self.read_sessions.setChecked(config.get("read_codex", True))
        form.addRow(self.read_sessions)
        layout.addLayout(form)
        save = QPushButton("保存运行设置")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self.style = StyleResources(config)
        self.style_status = QLabel()
        self.style_status.setWordWrap(True)
        layout.addWidget(self.style_status)
        self.sync_style_button = QPushButton("同步 user-style")
        self.sync_style_button.setEnabled(not config.get("demo"))
        self.sync_style_button.clicked.connect(self.sync_style)
        layout.addWidget(self.sync_style_button)
        self.refresh_style()
        self.message = QLabel("默认使用内置 prose 规范；user-style 使用私人镜像，仅点击同步时更新。先保存源目录再同步。")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch()

    def refresh_style(self):
        status = self.style.status()
        self.style_status.setText(status["message"] + ("\n上次同步：" + status["synced_at"] if status.get("available") else ""))

    def sync_style(self):
        try:
            if self.fields["zf_root"].text().strip() != self.config.get("zf_root", ""):
                raise DiaryError("请先保存 user-style 同步源目录")
            self.style.sync()
            self.message.setText("user-style 已同步；下次生成使用此快照。")
        except (OSError, ValueError) as error:
            self.message.setText("同步失败，原镜像保留：" + str(error))
        self.refresh_style()

    def save(self):
        runtime = {k: w.text().strip() for k, w in self.fields.items()}
        runtime["read_codex"] = self.read_sessions.isChecked()
        if runtime["prose_path"] and not Path(runtime["prose_path"]).is_absolute():
            self.message.setText("自定义 prose_path 必须为绝对路径；留空使用内置规范")
            return
        for key in ("codex_cli", "zf_root", "staging_root"):
            if key == "zf_root" and not runtime[key]:
                continue
            if not runtime[key] or not Path(runtime[key]).is_absolute():
                self.message.setText(f"{'user-style 同步源目录' if key == 'zf_root' else key} 必须为绝对路径")
                return
        try:
            self.settings.update(runtime=runtime)
            self.config.update(runtime)
            self.message.setText("运行设置已保存，下次任务使用最新配置。")
        except OSError as error:
            self.message.setText(str(error))


def cycle_range(request):
    return " — ".join(datetime.fromisoformat(request[key]).strftime("%m-%d %H:%M") for key in ("start", "end"))


class CycleStatus(QWidget):
    """Session-only automatic outcomes; durable reports stay in DiaryLibrary."""
    open_requested = Signal(str)
    retry_requested = Signal(str)

    def __init__(self, cycles, jobs):
        super().__init__()
        self.cycles, self.jobs = cycles, jobs
        self.results, self.rows = {}, {}
        self.setObjectName("cycleStatus")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(4)
        for row in cycles.overview():
            kind = row["kind"]
            line = QHBoxLayout()
            label = QLabel()
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            open_button, retry = QPushButton("查看报告"), QPushButton("重试")
            open_button.clicked.connect(lambda checked=False, k=kind: self.open_requested.emit(self.results[k]["entry_id"]))
            retry.clicked.connect(lambda checked=False, k=kind: self.retry_requested.emit(k))
            line.addWidget(label, 1)
            line.addWidget(open_button)
            line.addWidget(retry)
            layout.addLayout(line)
            self.rows[kind] = {"label": label, "open": open_button, "retry": retry}
        jobs.observe(self.update_task)

    def update_task(self, state):
        request = state.get("request", {})
        if request.get("automatic") and not state["pending"]:
            result = self.results.setdefault(request["kind"], {})
            result["error"] = state.get("error")
            if state.get("entry_id"):
                result.update(entry_id=state["entry_id"], request=deepcopy(request))
        self.refresh()

    def refresh(self):
        state = self.jobs.state
        running = state.get("request", {}) if state["pending"] else {}
        for row in self.cycles.overview():
            kind = row["kind"]
            widgets, result = self.rows[kind], self.results.get(kind, {})
            request = row["request"]
            if running.get("automatic") and running["kind"] == kind:
                text = cycle_range(running) + " · " + state["stage"]
            elif row["blocked"] and request:
                text = cycle_range(request) + " · " + (result.get("error") or "生成失败") + "，等待重试"
            elif request:
                text = cycle_range(request) + " · 等待补做"
            elif result.get("entry_id"):
                text = cycle_range(result["request"]) + " · 已完成"
            else:
                text = "下次 " + datetime.fromisoformat(row["next_due"]).strftime("%m-%d %H:%M") if row["enabled"] else "自动生成已关闭"
            widgets["label"].setText(KINDS[kind] + "：" + text)
            widgets["open"].setVisible(bool(result.get("entry_id")))
            widgets["retry"].setVisible(bool(row["blocked"] and request))
            widgets["retry"].setEnabled(not state["pending"])


class CyclePage(QWidget):
    retry_requested = Signal(str)
    settings_changed = Signal()

    def __init__(self, settings, cycles, jobs):
        super().__init__()
        self.settings, self.cycles, self.jobs = settings, cycles, jobs
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.addWidget(heading("周期设置"))
        note = QLabel("打开后立即检查补做；仅在程序打开期间运行。同类积压合并一份，覆盖至最近一次配置的执行时刻。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(3, 6)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalHeaderLabels(["内容", "自动生成", "间隔", "下次执行", "状态", "重试"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.controls = {}
        self.units = {}
        self.retry_buttons = {}
        for row, snapshot in enumerate(cycles.overview()):
            kind = snapshot["kind"]
            rule = settings.data["cycles"][kind]
            enabled = Switch()
            enabled.setChecked(rule["enabled"])
            days = QSpinBox()
            days.setRange(1, 366)
            weeks = rule["days"] % 7 == 0
            days.setValue(rule["days"] // 7 if weeks else rule["days"])
            units = QComboBox()
            units.addItem("天", 1)
            units.addItem("周", 7)
            units.setCurrentIndex(1 if weeks else 0)
            self.units[kind] = units
            interval = QWidget()
            interval_layout = QHBoxLayout(interval)
            interval_layout.setContentsMargins(6, 4, 6, 4)
            interval_layout.addWidget(days)
            interval_layout.addWidget(units)
            switch_host = QWidget()
            switch_layout = QHBoxLayout(switch_host)
            switch_layout.setContentsMargins(14, 4, 14, 4)
            switch_layout.addWidget(enabled)
            switch_layout.addStretch()
            self.controls[kind] = (enabled, days)
            self.table.setItem(row, 0, QTableWidgetItem(KINDS[kind]))
            self.table.setCellWidget(row, 1, switch_host)
            self.table.setCellWidget(row, 2, interval)
            retry = QPushButton("重试")
            retry.clicked.connect(lambda checked=False, k=kind: self.retry_requested.emit(k))
            self.retry_buttons[kind] = retry
            self.table.setCellWidget(row, 5, retry)
            self.table.setRowHeight(row, 64)
        self.table.setFixedHeight(255)
        layout.addWidget(self.table)
        time_row = QHBoxLayout()
        self.clock = QTimeEdit()
        self.clock.setDisplayFormat("HH:mm")
        anchor = datetime.fromisoformat(next(iter(settings.data["cycles"].values()))["anchor"])
        self.clock.setTime(QTime(anchor.hour, anchor.minute))
        time_row.addWidget(QLabel("本机执行时间"))
        time_row.addWidget(self.clock)
        time_row.addStretch()
        save = QPushButton("保存周期设置")
        save.clicked.connect(self.save)
        time_row.addWidget(save)
        layout.addLayout(time_row)
        layout.addSpacing(35)
        layout.addWidget(heading("生成任务"))
        self.task = QLabel()
        self.task.setWordWrap(True)
        layout.addWidget(self.task)
        actions = QHBoxLayout()
        cancel = QPushButton("取消当前任务")
        cancel.clicked.connect(jobs.cancel)
        actions.addWidget(cancel)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        jobs.observe(self.update_task)
        self.refresh()

    def save(self):
        try:
            rules = deepcopy(self.settings.data["cycles"])
            for kind, (enabled, days) in self.controls.items():
                rules[kind].update(enabled=enabled.isChecked(), days=days.value() * self.units[kind].currentData())
                anchor = datetime.fromisoformat(rules[kind]["anchor"])
                rules[kind]["anchor"] = anchor.replace(hour=self.clock.time().hour(), minute=self.clock.time().minute()).isoformat()
            self.settings.update(cycles=rules)
            self.cycles.blocked.clear()
            self.refresh()
            self.settings_changed.emit()
        except (OSError, ValueError) as error:
            self.task.setText(str(error))

    def refresh(self):
        state = self.jobs.state
        running = state.get("request", {}) if state["pending"] else {}
        for index, row in enumerate(self.cycles.overview()):
            kind = row["kind"]
            due = datetime.fromisoformat(row["next_due"])
            status = "等待手动重试" if row["blocked"] else "等待补做" if row["request"] else "等待到期"
            if not row["enabled"]:
                status = "已关闭"
            if running.get("automatic") and running["kind"] == kind:
                status = "生成中"
            self.table.setItem(index, 3, QTableWidgetItem(due.strftime("%Y-%m-%d %H:%M") if row["enabled"] else "已关闭"))
            self.table.setItem(index, 4, QTableWidgetItem(status))
            self.retry_buttons[kind].setEnabled(bool(row["blocked"] and row["request"] and not state["pending"]))

    def update_task(self, state):
        self.task.setText(state["stage"] + ("\n" + state["error"] if state.get("error") else ""))
        self.refresh()


class SourcePage(QWidget):
    def __init__(self, settings, sources):
        super().__init__()
        self.settings, self.sources = settings, sources
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.addWidget(heading("资料来源"))
        note = QLabel("Git 集合只发现直接子项目。普通目录用于工作总结，首次保存将现有文本和 PPTX 建为背景；以后按内容变化纳入，并说明迟到材料的时间限制。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["启用", "路径", "读取方式"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        for label, action in (("添加目录", self.add), ("移除选中目录", self.remove), ("保存登记表", self.save), ("导入 ChatGPT／文本", self.import_file)):
            button = QPushButton(label)
            if sources.config.get("demo") and label in ("添加目录", "导入 ChatGPT／文本"):
                button.setEnabled(False)
                button.setToolTip("演示模式不读取真实文件")
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.imported = QListWidget()
        layout.addWidget(self.imported)
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        for source in self.settings.data["sources"]:
            self.add_row(source)
        self.imported.clear()
        for item in self.settings.data["imports"]:
            self.imported.addItem(f"{item['name']} · {item['count']} 条文本 · {item['imported_at'][:10]}")

    def add_row(self, source):
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QCheckBox()
        enabled.setChecked(source.get("enabled", True))
        path = QTableWidgetItem(source["path"])
        path.setData(Qt.UserRole, source["id"])
        mode = QComboBox()
        mode.addItem("单个 Git 项目", "git")
        mode.addItem("直接子项目集合", "projects")
        mode.addItem("普通目录（工作资料）", "directory")
        mode.setCurrentIndex(mode.findData(source.get("type", "git")))
        self.table.setCellWidget(row, 0, enabled)
        self.table.setItem(row, 1, path)
        self.table.setCellWidget(row, 2, mode)
        self.table.setRowHeight(row, 50)

    def add(self):
        path = QFileDialog.getExistingDirectory(self, "登记资料目录")
        if path:
            self.add_row({"id": uuid4().hex, "path": path, "enabled": True, "type": "git"})

    def remove(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())

    def save(self):
        values = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if not Path(item.text()).is_absolute():
                self.message.setText("登记路径必须为绝对路径")
                return
            values.append({"id": item.data(Qt.UserRole), "path": item.text(), "enabled": self.table.cellWidget(row, 0).isChecked(),
                           "type": self.table.cellWidget(row, 2).currentData()})
        try:
            self.sources.register(values)
            self.message.setText("登记表已保存。")
        except (OSError, DiaryError) as error:
            self.message.setText(str(error))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入对话或文本", filter="对话与文本 (*.zip *.json *.md *.txt)")
        if path:
            try:
                count = self.sources.import_file(path)
                self.refresh()
                self.message.setText(f"已导入 {count} 条文本。" if count else "该文件已导入，未重复添加。")
            except Exception as error:
                self.message.setText("导入失败，既有记录未改动：" + str(error))


class ReportPage(QWidget):
    def __init__(self, reports, settings, jobs):
        super().__init__()
        self.reports, self.settings, self.jobs = reports, settings, jobs
        self.extra_paths = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.addWidget(heading("主题汇报"))
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        tabs = QTabWidget()
        form_widget = QWidget()
        form = QVBoxLayout(form_widget)
        form.addWidget(QLabel("主题"))
        topic_row = QHBoxLayout()
        self.topic = QComboBox()
        self.topic.currentIndexChanged.connect(self.topic_changed)
        topic_row.addWidget(self.topic, 1)
        manage = QPushButton("管理主题")
        manage.clicked.connect(self.manage_topics)
        topic_row.addWidget(manage)
        form.addLayout(topic_row)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName("muted")
        form.addWidget(self.description)
        form.addSpacing(14)
        form.addWidget(QLabel("时间范围（包含结束当天）"))
        dates = QHBoxLayout()
        self.start, self.end = date_input(QDate.currentDate().addDays(-20)), date_input()
        dates.addWidget(self.start)
        dates.addWidget(QLabel("—"))
        dates.addWidget(self.end)
        form.addLayout(dates)
        form.addWidget(QLabel("补充要求"))
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("说明关注内容、所需数据及文件格式。额外绝对路径可单独占一行或使用引号。")
        form.addWidget(self.prompt, 1)
        checks = QHBoxLayout()
        self.include = {}
        for key in ("diary", "development", "work"):
            check = QCheckBox(KINDS[key])
            check.setChecked(True)
            self.include[key] = check
            checks.addWidget(check)
        self.zf = QCheckBox("user-style 风格")
        checks.addWidget(self.zf)
        form.addLayout(checks)
        add = QPushButton("本次补充资料…")
        add.setEnabled(not jobs.config.get("demo"))
        add.clicked.connect(self.add_extra)
        form.addWidget(add)
        self.extra = QLabel()
        self.extra.setWordWrap(True)
        form.addWidget(self.extra)
        form.addWidget(QLabel("输出目录"))
        output = QHBoxLayout()
        self.output = QLineEdit()
        self.output.setPlaceholderText("选择本机目录")
        choose = QPushButton("选择…")
        choose.clicked.connect(self.choose_output)
        output.addWidget(self.output, 1)
        output.addWidget(choose)
        form.addLayout(output)
        self.generate = QPushButton("生成材料包")
        self.generate.setObjectName("primary")
        self.generate.clicked.connect(self.submit)
        form.addWidget(self.generate)
        warning = QLabel(NOTICE)
        warning.setWordWrap(True)
        warning.setObjectName("muted")
        form.addWidget(warning)
        tabs.addTab(form_widget, "新建汇报")
        self.history = QListWidget()
        self.history.currentRowChanged.connect(self.select_report)
        tabs.addTab(self.history, "历史汇报")
        splitter.addWidget(tabs)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(heading("材料包预览"))
        self.files = QListWidget()
        self.files.setMaximumHeight(190)
        self.files.currentTextChanged.connect(self.preview_file)
        right_layout.addWidget(self.files)
        self.preview_stack = QStackedWidget()
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.setPlainText("生成后的正文、证据与数据会在这里显示。")
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.pdf_document = QPdfDocument(self)
        self.pdf = QPdfView()
        self.pdf.setDocument(self.pdf_document)
        self.pdf.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        for widget in (self.preview, self.image, self.pdf): self.preview_stack.addWidget(widget)
        right_layout.addWidget(self.preview_stack, 1)
        self.open_output = QPushButton("打开输出目录")
        self.open_output.setEnabled(False)
        self.open_output.clicked.connect(self.open_folder)
        right_layout.addWidget(self.open_output)
        splitter.addWidget(right)
        splitter.setSizes([540, 580])
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.current_report = None
        self.refresh()
        jobs.observe(self.job_changed)

    def refresh(self):
        self.topic.clear()
        for topic in self.settings.data["topics"]:
            self.topic.addItem(topic["name"], topic)
        self.history.clear()
        for report in self.settings.data["reports"]:
            self.history.addItem(report["start"][:10] + " — " + report["end"][:10] + "\n" + report["title"])

    def topic_changed(self):
        topic = self.topic.currentData() or {}
        self.description.setText(topic.get("description", "请先添加一个主题"))

    def manage_topics(self):
        topic = deepcopy(self.topic.currentData() or {})
        dialog = QDialog(self)
        dialog.setWindowTitle("管理主题")
        layout = QFormLayout(dialog)
        name = QLineEdit(topic.get("name", ""))
        description = QTextEdit(topic.get("description", ""))
        prompt = QTextEdit(topic.get("prompt", ""))
        layout.addRow("名称", name)
        layout.addRow("目标与边界", description)
        layout.addRow("默认 prompt", prompt)
        actions = QHBoxLayout()
        def save(as_new=False):
            try:
                self.reports.save_topic({"id": None if as_new else topic.get("id"), "name": name.text(),
                    "description": description.toPlainText(), "prompt": prompt.toPlainText()})
                self.refresh()
                dialog.accept()
            except DiaryError as error:
                QMessageBox.warning(dialog, "检查主题", str(error))
        def remove():
            if topic and QMessageBox.question(dialog, "移除主题", "移除这个主题？已生成的材料包仍保留。") == QMessageBox.Yes:
                self.reports.remove_topic(topic["id"])
                self.refresh()
                dialog.accept()
        for label, action in (("保存修改", lambda: save()), ("另存新主题", lambda: save(True)), ("移除主题", remove)):
            button = QPushButton(label)
            button.clicked.connect(action)
            actions.addWidget(button)
        layout.addRow(actions)
        dialog.exec()

    def add_extra(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "本次额外资料（不会自动登记）")
        self.extra_paths = list(dict.fromkeys([*self.extra_paths, *paths]))
        self.extra.setText("\n".join(self.extra_paths))

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择材料包输出目录")
        if path:
            self.output.setText(path)

    def submit(self):
        try:
            topic = self.topic.currentData()
            if not topic:
                raise DiaryError("请先创建一个主题")
            request = {"kind": "report", "start": datetime.combine(self.start.date().toPython(), datetime.min.time()).astimezone().isoformat(),
                "end": datetime.combine(self.end.date().addDays(1).toPython(), datetime.min.time()).astimezone().isoformat(),
                "topic": topic, "prompt": topic.get("prompt", "") + "\n" + self.prompt.toPlainText(),
                "include": [k for k, check in self.include.items() if check.isChecked()], "zf": self.zf.isChecked(),
                "extra_paths": self.extra_paths, "output_dir": self.output.text().strip()}
            self.jobs.submit(request)
        except (DiaryError, OSError) as error:
            self.message.setText(str(error))

    def job_changed(self, state):
        self.generate.setEnabled(not state["pending"])
        if state.get("request", {}).get("kind") == "report":
            self.message.setText(state["stage"] + ("：" + state["error"] if state.get("error") else ""))
            if not state["pending"] and state.get("report"):
                self.refresh()
                self.history.setCurrentRow(self.history.count() - 1)

    def select_report(self, row):
        if row < 0:
            return
        self.current_report = self.settings.data["reports"][row]
        self.files.clear()
        self.files.addItems(self.current_report["files"])
        self.open_output.setEnabled(True)
        if self.files.count(): self.files.setCurrentRow(0)

    def preview_file(self, name):
        if not name or not self.current_report:
            return
        try:
            if Path(name).name != name:
                raise DiaryError("无效材料路径")
            path = Path(self.current_report["path"]) / name
            self.preview_stack.setCurrentIndex(0)
            if path.suffix.lower() in (".png", ".svg"):
                pixmap = QPixmap(str(path))
                self.image.setPixmap(pixmap.scaled(700, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.preview_stack.setCurrentIndex(1)
            elif path.suffix.lower() == ".pdf":
                self.pdf_document.close()
                self.pdf_document.load(str(path))
                self.preview_stack.setCurrentIndex(2)
            elif path.suffix.lower() == ".md":
                self.preview.setMarkdown(path.read_text(encoding="utf-8"))
            elif path.suffix.lower() == ".html":
                self.preview.setHtml(path.read_text(encoding="utf-8"))
            else:
                self.preview.setPlainText(path.read_text(encoding="utf-8"))
        except (OSError, DiaryError) as error:
            self.preview.setPlainText(str(error))

    def open_folder(self):
        if self.current_report:
            self.message.setText(NOTICE)
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_report["path"]))
