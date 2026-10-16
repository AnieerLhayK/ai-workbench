"""Native editing and confirmation forms; a failed commit never closes a draft."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                              QPlainTextEdit, QComboBox, QVBoxLayout, QLabel, QFileDialog,
                              QHBoxLayout, QPushButton)

from .model import STATUSES, StoreError
from .style import STYLE


class ErrorLabel(QLabel):
    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self):
        self.setText("")


def text_label(text, name=""):
    label = ErrorLabel(text) if name == "error" else QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setObjectName(name)
    if name == "error":
        label.setVisible(bool(text))
    return label


class TrialDialog(QDialog):
    def __init__(self, store, trial=None, parent=None):
        super().__init__(parent)
        self.store, self.trial_id = store, trial["id"] if trial else None
        self.expected_version = trial.get("revision", 1) if trial else None
        self.saved_id = None
        self.setWindowTitle("编辑试验" if trial else "新建试验")
        self.setStyleSheet(STYLE)
        self.resize(700, 780)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        form = QFormLayout()
        form.setSpacing(14)
        self.fields = {}
        values = trial or {}
        for key, title in (("name", "名称"), ("source", "来源链接"), ("tags", "标签（逗号分隔）"),
                           ("goal", "试验目标"), ("directory", "工作目录"), ("command", "PowerShell 命令"),
                           ("next_action", "下一步")):
            field = QPlainTextEdit() if key in ("goal", "command") else QLineEdit()
            field.setObjectName(key)
            field.setAccessibleName(title)
            if isinstance(field, QPlainTextEdit):
                field.setMaximumHeight(90)
                field.setTabChangesFocus(True)
                field.setPlainText(values.get(key, ""))
            else:
                field.setText("，".join(values.get("tags", [])) if key == "tags" else values.get(key, ""))
            self.fields[key] = field
            label = text_label(title)
            label.setBuddy(field)
            if key == "directory":
                row = QHBoxLayout()
                row.addWidget(field)
                choose = QPushButton("选择")
                choose.clicked.connect(self.choose_directory)
                row.addWidget(choose)
                form.addRow(label, row)
            else:
                form.addRow(label, field)
        self.status = QComboBox()
        self.status.setAccessibleName("试验状态")
        self.status.addItems(STATUSES)
        self.status.setCurrentText(values.get("status", STATUSES[0]))
        form.addRow("状态", self.status)
        layout.addLayout(form)
        layout.addWidget(text_label("目录与命令可稍后填写；启动前会再次确认。", "muted"))
        self.error = text_label("", "error")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.fields["name"].setFocus()

    def choose_directory(self):
        value = QFileDialog.getExistingDirectory(self, "选择试验工作目录", self.fields["directory"].text())
        if value:
            self.fields["directory"].setText(value)

    def save(self):
        values = {key: field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()
                  for key, field in self.fields.items()}
        values["tags"] = values["tags"].replace("，", ",").split(",")
        values["status"] = self.status.currentText()
        try:
            from .service import ExperimentService
            self.saved_id = (self.store.save(values, self.trial_id, self.expected_version) if isinstance(self.store, ExperimentService)
                             else self.store.save(values, self.trial_id))
        except StoreError as error:
            self.error.setText(str(error))
            return
        self.accept()


class ResultDialog(QDialog):
    def __init__(self, store, trial, parent=None):
        super().__init__(parent)
        self.store, self.trial_id = store, trial["id"]
        self.expected_version = trial.get("revision", 1)
        self.setWindowTitle("记录结果 · " + trial["name"])
        self.setStyleSheet(STYLE)
        self.resize(650, 550)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        form = QFormLayout()
        form.setSpacing(16)
        self.result_text = QPlainTextEdit()
        self.result_text.setObjectName("result")
        self.result_text.setAccessibleName("试验结果")
        self.result_text.setTabChangesFocus(True)
        self.paths = QPlainTextEdit()
        self.paths.setAccessibleName("关联文件路径，每行一个")
        self.paths.setMaximumHeight(110)
        self.paths.setTabChangesFocus(True)
        self.next_action = QLineEdit(trial["next_action"])
        self.next_action.setAccessibleName("下一步")
        form.addRow("试验结果", self.result_text)
        form.addRow("文件路径（每行一个）", self.paths)
        form.addRow("下一步", self.next_action)
        layout.addLayout(form)
        self.error = text_label("", "error")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存记录")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            self.store.record(self.trial_id, self.result_text.toPlainText(), self.next_action.text(), self.paths.toPlainText().splitlines(), self.expected_version)
        except StoreError as error:
            self.error.setText(str(error))
            return
        self.accept()


class ConfirmDialog(QDialog):
    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认启动试验")
        self.setStyleSheet(STYLE)
        self.resize(720, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(text_label(request.title, "sectionHeading"))
        layout.addWidget(text_label("工作目录"))
        layout.addWidget(text_label(request.project, "muted"))
        layout.addWidget(text_label("即将执行的 PowerShell 命令"))
        command = QPlainTextEdit(request.command)
        command.setReadOnly(True)
        layout.addWidget(command)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认并打开终端")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setFocus()
