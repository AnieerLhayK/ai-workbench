"""Native window composition; persistence and dispatch live behind Modules."""
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QLineEdit, QComboBox, QListWidget, QListWidgetItem,
                              QScrollArea, QFrame, QFormLayout, QPlainTextEdit, QDialog)

from .dialogs import TrialDialog, ResultDialog, ConfirmDialog, text_label
from .launch import command_request
from .model import STATUSES, StoreError
from .style import STYLE
from .icons import icon


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
    def __init__(self, store, launcher, *, demo=False, confirm=ConfirmDialog):
        super().__init__()
        self.store, self.launcher, self.demo, self.confirm = store, launcher, demo, confirm
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
        top.addStretch()
        self.create_button = button("新建试验", self.new_trial, primary=True)
        top.addWidget(self.create_button)
        outer.addWidget(header)
        body = QHBoxLayout()
        body.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(390)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(0, 22, 0, 0)
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
        right.setContentsMargins(28, 24, 26, 22)
        right.setSpacing(20)
        if demo:
            right.addWidget(text_label("演示数据", "muted"))
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
        goal_frame, goal_layout = panel("下一步")
        next_title = goal_layout.takeAt(0).widget()
        self.next_action = QLineEdit()
        self.next_action.setReadOnly(True)
        self.next_action.setAccessibleName("下一步")
        next_row = QHBoxLayout()
        next_row.addWidget(next_title)
        next_row.addSpacing(42)
        next_row.addWidget(self.next_action, 1)
        goal_layout.addLayout(next_row)
        fields = QFormLayout()
        fields.setHorizontalSpacing(22)
        fields.setVerticalSpacing(12)
        self.goal, self.source, self.tags = (text_label("") for _ in range(3))
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source.setStyleSheet("color: #61b9d0;")
        fields.addRow("试验目标", self.goal)
        fields.addRow("来源链接", self.source)
        fields.addRow("标签", self.tags)
        goal_layout.addLayout(fields)
        right.addWidget(goal_frame)
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
        self.launch_button = button("启动试验", self.start_trial, primary=True)
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
        self.records_frame, self.records_layout = panel("试验记录")
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
        footer = text_label("终端打开不代表试验成功", "muted")
        footer.setContentsMargins(28, 8, 26, 18)
        right_column_layout.addWidget(footer)
        body.addWidget(right_column, 1)
        outer.addLayout(body, 1)
        self.search.textChanged.connect(self.refresh_list)
        self.filter.currentTextChanged.connect(self.refresh_list)
        self.list.currentItemChanged.connect(self.select_trial)
        self.launcher.observe(self.dispatch_changed)
        self.refresh_list()

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
            item.setSizeHint(QSize(386, max(132, content.totalHeightForWidth(386))))
            self.list.setItemWidget(item, row)
            if trial["id"] == self.current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.list_empty.setText("" if visible else "尚无试验，点击新建试验" if not self.store.snapshot()["trials"] else "没有匹配的试验")
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
        self.heading.setText(trial["name"] if trial else "创建你的第一项试验")
        self.next_action.setText(trial["next_action"] if trial else "点击右上角新建试验")
        self.goal.setText(trial["goal"] if trial else "记录想尝试的工具、目标与下一步")
        self.source.setText(trial["source"] if trial else "")
        self.tags.setText(" · ".join(trial["tags"]) if trial else "")
        self.directory.setText(trial["directory"] if trial else "")
        self.command.setPlainText(trial["command"] if trial else "")
        self.edit_button.setEnabled(trial is not None)
        self.source_button.setEnabled(bool(trial and trial["source"]))
        self.record_button.setEnabled(trial is not None)
        self.launch_button.setEnabled(trial is not None and not self.launcher.state.pending)
        while self.records_layout.count() > 1:
            item = self.records_layout.takeAt(1)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        records = trial["records"] if trial else []
        if not records:
            empty = text_label("尚无记录", "muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(100)
            self.records_layout.addWidget(empty)
        for record in reversed(records):
            when = datetime.fromisoformat(record["at"]).astimezone().strftime("%Y-%m-%d %H:%M")
            text = when + "\n" + record["result"] + "\n下一步：" + record["next_action"]
            if record["paths"]:
                text += "\n文件路径：\n" + "\n".join(record["paths"])
            self.records_layout.addWidget(text_label(text))

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
