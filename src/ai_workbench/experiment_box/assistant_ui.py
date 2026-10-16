"""Native conversation composer and immutable approval presentation."""
import json

from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
                              QListWidget, QScrollArea, QDialog, QDialogButtonBox, QFileDialog,
                              QInputDialog, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView)

from .assistant import SHORTCUTS
from .dialogs import text_label
from .style import STYLE
from .model import FIELD_LABELS


class AssistantPanel(QWidget):
    send = Signal(str, object)
    cancel = Signal()
    retry = Signal()
    def __init__(self):
        super().__init__()
        self.setObjectName("assistantPanel")
        self.setMinimumWidth(330)
        self.materials = []
        self.drafts = {}
        self.context = "overview"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        self.title = text_label("总览助手", "sectionHeading")
        header.addWidget(self.title)
        header.addStretch()
        self.auth = text_label("登录状态待检查", "muted")
        header.addWidget(self.auth)
        layout.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.messages = QWidget()
        self.message_layout = QVBoxLayout(self.messages)
        self.message_layout.setContentsMargins(0, 10, 0, 10)
        self.message_layout.setSpacing(16)
        self.scroll.setWidget(self.messages)
        layout.addWidget(self.scroll, 1)
        self.shortcuts = QListWidget()
        self.shortcuts.setAccessibleName("@ 快捷指令")
        self.shortcuts.addItems(list(SHORTCUTS))
        self.shortcuts.setMaximumHeight(220)
        self.shortcuts.hide()
        self.shortcuts.itemActivated.connect(self.use_shortcut)
        self.shortcuts.itemClicked.connect(self.use_shortcut)
        layout.addWidget(self.shortcuts)
        self.composer = QPlainTextEdit()
        self.composer.setAccessibleName("助手提示输入")
        self.composer.setPlaceholderText("输入要求，@ 呼出快捷指令")
        self.composer.setMinimumHeight(115)
        self.composer.setMaximumHeight(175)
        self.composer.installEventFilter(self)
        self.composer.textChanged.connect(self.shortcut_visibility)
        layout.addWidget(self.composer)
        row = QHBoxLayout()
        self.attach = QPushButton("附加资料")
        self.attach.clicked.connect(self.attach_material)
        row.addWidget(self.attach)
        self.stop = QPushButton("取消生成")
        self.stop.clicked.connect(self.cancel)
        self.stop.hide()
        row.addWidget(self.stop)
        self.submit = QPushButton("发送")
        self.submit.setObjectName("primary")
        self.submit.clicked.connect(self.submit_prompt)
        row.addWidget(self.submit)
        layout.addLayout(row)
        self.retry_button = QPushButton("重试保存上一轮结果")
        self.retry_button.clicked.connect(self.retry)
        self.retry_button.hide()
        layout.addWidget(self.retry_button)
        self.attachment_hint = text_label("仅使用本次附加资料", "muted")
        layout.addWidget(self.attachment_hint)

    def eventFilter(self, watched, event):
        if watched == self.composer and event.type() == QEvent.Type.KeyPress:
            if self.shortcuts.isVisible() and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self.shortcuts.setCurrentRow(0)
                self.shortcuts.setFocus()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.shortcuts.hide()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.submit_prompt()
                return True
        return super().eventFilter(watched, event)

    def shortcut_visibility(self):
        self.shortcuts.setVisible(self.composer.toPlainText().rstrip().endswith(("@", "＠")))

    def use_shortcut(self, item):
        self.composer.setPlainText(SHORTCUTS[item.text()])
        self.shortcuts.hide()
        self.composer.setFocus()

    def attach_material(self):
        kind, ok = QInputDialog.getItem(self, "附加本轮资料", "资料类型", ["文本或截图", "公开链接", "清空本轮附件"], 0, False)
        if not ok:
            return
        if kind == "清空本轮附件":
            self.materials.clear()
        elif len(self.materials) >= 5:
            self.attachment_hint.setText("每轮最多 5 项资料；可清空后重选")
            return
        elif kind == "文本或截图":
            path, _ = QFileDialog.getOpenFileName(self, "选择本轮明确附加的文件", "", "文本与截图 (*.txt *.md *.json *.csv *.py *.ps1 *.toml *.yaml *.yml *.log *.png *.jpg *.jpeg *.webp)")
            if path:
                self.materials.append(dict(type="file", value=path))
        else:
            url, ok = QInputDialog.getText(self, "附加公开资料", "HTTPS 链接（不跟随跳转）")
            if ok and url.strip():
                self.materials.append(dict(type="link", value=url.strip()))
        self.attachment_hint.setText(f"已附加 {len(self.materials)} 项 · 仅用于本轮；可在附加资料中清空")

    def submit_prompt(self):
        text = self.composer.toPlainText().strip()
        if text and self.submit.isEnabled():
            self.send.emit(text, list(self.materials))

    def accepted(self):
        self.composer.clear()
        self.materials.clear()
        self.attachment_hint.setText("仅使用本次附加资料")

    def render(self, context, conversation, pending, available):
        if context != self.context:
            self.drafts[self.context] = (self.composer.toPlainText(), list(self.materials))
            self.context = context
            text, attachments = self.drafts.get(context, ("", []))
            self.composer.setPlainText(text)
            self.materials = list(attachments)
        self.title.setText("总览助手" if context == "overview" else "试验助手")
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not conversation:
            self.message_layout.addWidget(text_label("告诉我你想尝试什么。\n我会整理内容，关键操作由你确认。", "muted"))
        for message in conversation:
            who = {"user": "你", "assistant": "Codex", "error": "请求状态"}[message["role"]]
            self.message_layout.addWidget(text_label(who + "  ·  " + message["at"][11:16], "muted"))
            bubble = text_label(message["text"])
            bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bubble.setObjectName("bubble")
            self.message_layout.addWidget(bubble)
        self.message_layout.addStretch()
        self.submit.setEnabled(available and not pending)
        self.submit.setText("生成中…" if pending else "发送")
        self.stop.setVisible(pending)


class ApprovalDialog(QDialog):
    def __init__(self, receipt, service, config, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self.resize(900, 850)
        self.setMinimumSize(700, 600)
        self.reject_request = False
        layout = QVBoxLayout(self)
        run = receipt["operations"][0]["action"] == "plan"
        blocked_reason = config.get("runner_disabled_reason", "") if run else ""
        layout.addWidget(text_label("批准本轮试验" if run else "确认试验变更", "heading"))
        layout.addWidget(text_label("核对本轮内容；变更后需重新确认。取消不会执行或保存提案。", "muted"))
        if blocked_reason:
            layout.addWidget(text_label("自动运行暂不可用：" + blocked_reason, "error"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        details = QVBoxLayout(contents)
        details.setContentsMargins(12, 8, 12, 12)
        snapshot = service.snapshot()
        for op in receipt["operations"]:
            trial = next((t for t in snapshot["trials"] if t["id"] == op.get("trial_id")), {})
            details.addWidget(text_label(trial.get("name", "新建试验"), "sectionHeading"))
            if op["action"] == "plan":
                from .runner import command
                details.addWidget(text_label("目标\n" + op["goal"]))
                root = str(service.work_root(op["trial_id"]))
                details.addWidget(text_label("读取、写入与输出：仅本试验空间\n" + root + "\n另只读运行环境；网络：禁止\n时限：" + str(op["timeout_seconds"]) + " 秒", "muted"))
                details.addWidget(text_label("拟改文件", "sectionHeading"))
                files = QTableWidget(len(op["files"]), 2)
                files.setHorizontalHeaderLabels(["操作", "文件"])
                files.verticalHeader().hide()
                files.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                files.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                files.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
                files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                files.setMaximumHeight(135)
                original = receipt["base"][op["trial_id"]]["files"]
                for index, file in enumerate(op["files"]):
                    files.setItem(index, 0, QTableWidgetItem("修改" if file["path"] in original else "新建"))
                    files.setItem(index, 1, QTableWidgetItem(file["path"]))
                details.addWidget(files)
                preview = QPlainTextEdit()
                preview.setReadOnly(True)
                preview.setMinimumHeight(140)
                preview.setMaximumHeight(180)
                def show_file(index, edit=preview, values=op["files"]):
                    edit.setPlainText(values[index]["content"] if index >= 0 else "无文件变更")
                files.currentCellChanged.connect(lambda row, column, old_row, old_column, display=show_file: display(row))
                if op["files"]:
                    files.setCurrentCell(0, 1)
                show_file(0 if op["files"] else -1)
                details.addWidget(preview)
                try:
                    complete_command = subprocess_list(command(config, op))
                except ValueError as error:
                    complete_command = "运行环境未配置：" + str(error)
                details.addWidget(text_label("完整执行命令", "sectionHeading"))
                details.addWidget(text_label(complete_command))
            elif op["action"] in ("create", "update"):
                for key, value in op["fields"].items():
                    details.addWidget(text_label(FIELD_LABELS[key] + "\n原值：" + str(trial.get(key, "")) + "\n建议：" + str(value)))
            else:
                details.addWidget(text_label(json.dumps(op, ensure_ascii=False, indent=2)))
        binding = text_label("来源：" + {"cli": "CLI", "assistant": "Codex"}.get(receipt["origin"], receipt["origin"]) + " · 本次批准仅适用于当前内容与文件。", "muted")
        binding.setToolTip("计划校验：" + receipt["plan_hash"])
        details.addWidget(binding)
        scroll.setWidget(contents)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("批准并运行" if run else "确认变更")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not blocked_reason)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        reject = buttons.addButton("退回修改", QDialogButtonBox.ButtonRole.ActionRole)
        def return_for_revision():
            self.reject_request = True
            self.reject()
        reject.clicked.connect(return_for_revision)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setFocus()


def subprocess_list(arguments):
    import subprocess
    return subprocess.list2cmdline(arguments)
