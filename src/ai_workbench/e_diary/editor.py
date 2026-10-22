"""Diary editor and period reader. Persistence is crossed only through DiaryLibrary."""
from copy import deepcopy
from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QDateEdit,
    QPushButton, QLabel, QTextEdit, QTextBrowser, QStackedWidget, QComboBox, QDialog,
    QListWidget, QDialogButtonBox, QMessageBox, QScrollArea, QMenu)

from .library import Conflict, DiaryError, period_label
from .reports import paint_chart
from .style import is_dark


class Chart(QWidget):
    def __init__(self, chart, settings):
        super().__init__()
        self.chart, self.settings = chart, settings
        self.setMinimumHeight(230)

    def paintEvent(self, event):
        paint_chart(self, self.chart, dark=is_dark(self.settings.data["theme"]), width=self.width(), height=self.height())


class Editor(QWidget):
    saved = Signal(str)
    regenerate = Signal(object)
    compare = Signal(object)

    def __init__(self, library, settings):
        super().__init__()
        self.library, self.settings = library, settings
        self.record = None
        self.loading, self.dirty, self.conflicted = False, False, False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(800)
        self.timer.timeout.connect(self.save)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        header = QHBoxLayout()
        self.date = QDateEdit(QDate.currentDate())
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setCalendarPopup(True)
        self.period = QLabel()
        self.status = QLabel("尚未保存")
        self.status.setObjectName("muted")
        self.regen = QPushButton("重新生成")
        self.regen.clicked.connect(lambda: self.regenerate.emit(self.record))
        self.comparison = QPushButton("生成对比版")
        self.comparison.clicked.connect(lambda: self.compare.emit(self.record))
        overflow = QPushButton("…")
        menu = QMenu(overflow)
        menu.addAction("查看历史版本", self.history)
        self.remove = menu.addAction("删除这篇记录", self.delete)
        overflow.setMenu(menu)
        header.addWidget(self.date)
        header.addStretch()
        for widget in (self.status, self.regen, self.comparison, overflow): header.addWidget(widget)
        outer.addLayout(header)
        outer.addWidget(self.period)
        self.title = QLineEdit()
        self.title.setObjectName("title")
        self.title.setPlaceholderText("今天想记些什么")
        outer.addWidget(self.title)
        self.generated_label = QLabel("生成内容 · 可编辑")
        self.generated_label.setObjectName("muted")
        outer.addWidget(self.generated_label)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("标签，以逗号分隔")
        outer.addWidget(self.tags)
        self.toolbar_widget = QWidget()
        toolbar = QHBoxLayout(self.toolbar_widget)
        toolbar.setContentsMargins(0, 0, 0, 0)
        for label, marker in (("B", "**"), ("I", "*"), ("标题", "## "), ("列表", "- "), ("引用", "> ")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, m=marker: self.markup(m))
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.extension = QComboBox()
        self.extension.addItems([".md", ".txt"])
        self.extension.currentTextChanged.connect(self.changed)
        toolbar.addWidget(self.extension)
        self.preview_button = QPushButton("预览")
        self.preview_button.clicked.connect(self.toggle_preview)
        header.addWidget(self.preview_button)
        outer.addWidget(self.toolbar_widget)
        self.stack = QStackedWidget()
        self.body = QTextEdit()
        self.body.setAcceptRichText(False)
        self.body.setStyleSheet("QTextEdit { font-size:22px; }")
        self.reading = QWidget()
        self.read_layout = QVBoxLayout(self.reading)
        self.read_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = QTextBrowser()
        self.preview.setStyleSheet("QTextBrowser { font-size:20px; border:0; padding:12px; }")
        self.preview.setOpenExternalLinks(False)
        self.preview.setOpenLinks(False)
        self.read_layout.addWidget(self.preview, 1)
        self.chart = None
        self.stack.addWidget(self.body)
        self.stack.addWidget(self.reading)
        outer.addWidget(self.stack, 1)
        footer = QHBoxLayout()
        self.sources = QPushButton("查看依据")
        self.sources.clicked.connect(self.show_sources)
        self.restore = QPushButton("从回收站恢复")
        self.restore.clicked.connect(self.restore_record)
        footer.addWidget(self.sources)
        footer.addWidget(self.restore)
        footer.addStretch()
        self.count = QLabel()
        self.count.setObjectName("muted")
        footer.addWidget(self.count)
        outer.addLayout(footer)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName("message")
        outer.addWidget(self.message)
        conflict = QHBoxLayout()
        self.reload_button = QPushButton("载入外部版本")
        self.reload_button.clicked.connect(self.reload_external)
        self.keep_button = QPushButton("将我的编辑另存为日记")
        self.keep_button.clicked.connect(self.keep_draft)
        conflict.addWidget(self.reload_button)
        conflict.addWidget(self.keep_button)
        outer.addLayout(conflict)
        self.reload_button.hide()
        self.keep_button.hide()
        self.title.textChanged.connect(self.changed)
        self.tags.textChanged.connect(self.changed)
        self.body.textChanged.connect(self.changed)
        self.date.dateChanged.connect(self.changed)
        self.clear()

    def clear(self, kind="diary"):
        self.timer.stop()
        self.loading = True
        self.record = None
        self.dirty = self.conflicted = False
        for widget in (self.title, self.tags, self.body):
            widget.clear()
        self.status.setText("暂无记录")
        self.count.clear()
        self.message.clear()
        self.period.clear()
        for widget in (self.generated_label, self.regen, self.comparison, self.sources, self.restore,
                       self.reload_button, self.keep_button, self.period):
            widget.hide()
        self.date.setVisible(kind == "diary")
        self.tags.setVisible(kind == "diary")
        self.toolbar_widget.setVisible(kind == "diary")
        self.preview_button.hide()
        self.body.setPlaceholderText("点击左侧「新建日记」开始记录。" if kind == "diary"
                                     else "选择时期查看记录，或点击「立即生成」。" if kind != "trash"
                                     else "回收站中暂无选中的记录。")
        self.stack.setCurrentIndex(0)
        self.update_preview()
        self.loading = False
        self.setEnabled(False)

    def changed(self, *args):
        if not self.loading and self.record and not self.record.get("deleted"):
            self.dirty = True
            self.status.setText("正在编辑")
            self.count.setText(f"{len(self.body.toPlainText())} 字")
            if not self.conflicted:
                self.timer.start()

    def markup(self, marker):
        cursor = self.body.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(marker + selected + (marker if marker in ("*", "**") else ""))

    def load(self, record):
        self.timer.stop()
        self.loading = True
        self.record = deepcopy(record)
        self.setEnabled(True)
        self.preview_button.show()
        self.title.setText(record["title"])
        self.date.setDate(QDate.fromString(record["date"], "yyyy-MM-dd"))
        self.tags.setText(", ".join(record.get("tags", [])))
        self.extension.setCurrentText(record.get("format", ".md"))
        self.body.setPlainText(record["body"])
        block = QTextBlockFormat()
        block.setLineHeight(175, 1)
        cursor = QTextCursor(self.body.document())
        cursor.select(QTextCursor.Document)
        cursor.mergeBlockFormat(block)
        self.period.setText(period_label(record.get("period")))
        summary = record["kind"] != "diary"
        self.generated_label.setVisible(summary)
        self.date.setVisible(not summary)
        self.period.setVisible(summary)
        deleted = record.get("deleted", False)
        self.regen.setVisible(summary and not deleted)
        self.comparison.setVisible(summary and not deleted and record["kind"] in ("development", "work"))
        self.sources.setVisible(summary)
        self.restore.setVisible(deleted)
        self.remove.setText("永久删除" if deleted else "删除")
        for widget in (self.title, self.tags, self.date, self.extension): widget.setEnabled(not deleted)
        self.body.setReadOnly(deleted)
        self.dirty, self.conflicted = False, False
        self.loading = False
        self.status.setText("已保存" if record.get("id") else "新日记")
        self.count.setText(f"{len(record['body'])} 字")
        self.message.clear()
        self.reload_button.hide()
        self.keep_button.hide()
        self.stack.setCurrentIndex(1 if summary or deleted else 0)
        self.toolbar_widget.setVisible(not summary and not deleted)
        self.tags.setVisible(not summary and not deleted)
        self.preview_button.setText("编辑" if self.stack.currentIndex() else "预览")
        self.update_preview()

    def fields(self):
        record = deepcopy(self.record)
        record.update(title=self.title.text(), date=self.date.date().toString("yyyy-MM-dd"),
                      body=self.body.toPlainText(), tags=[t.strip() for t in self.tags.text().replace("，", ",").split(",") if t.strip()],
                      format=self.extension.currentText())
        return record

    def save(self):
        self.timer.stop()
        if not self.record or not self.dirty:
            return not self.conflicted
        try:
            record = self.library.save(self.fields(), self.record.get("id"), self.record.get("hash"))
        except Conflict as error:
            self.conflicted = True
            self.message.setText(str(error))
            self.reload_button.show()
            self.keep_button.show()
            return False
        except (OSError, DiaryError) as error:
            self.status.setText("保存失败，编辑仍保留")
            self.message.setText(str(error))
            return False
        self.record = record
        self.dirty = False
        self.status.setText("已保存")
        self.message.clear()
        self.saved.emit(record["id"])
        return True

    def check_external(self):
        if not self.record or not self.record.get("id"):
            return
        try:
            external = self.library.read(self.record["id"])
            if external["hash"] != self.record["hash"]:
                if self.dirty:
                    self.save()
                else:
                    self.load(external)
        except (OSError, DiaryError, KeyError) as error:
            self.message.setText(str(error))

    def reload_external(self):
        if QMessageBox.question(self, "保留编辑", "载入外部版本前，将当前编辑另存为一篇日记？") == QMessageBox.Yes:
            self.keep_draft()
        else:
            self.load(self.library.read(self.record["id"]))

    def keep_draft(self):
        try:
            fields = self.fields()
            fields.update(kind="diary", title=fields["title"] + "（冲突副本）")
            saved = self.library.save(fields)
            self.load(saved)
            self.saved.emit(saved["id"])
        except (OSError, DiaryError) as error:
            self.message.setText(str(error))

    def update_preview(self):
        text = self.body.toPlainText()
        self.preview.document().setDefaultStyleSheet("p { line-height:180%; margin-bottom:20px; }")
        if self.extension.currentText() == ".md":
            self.preview.setMarkdown(text)
        else:
            self.preview.setPlainText(text)
        block = QTextBlockFormat()
        block.setLineHeight(175, 1)
        block.setBottomMargin(18)
        cursor = QTextCursor(self.preview.document())
        cursor.select(QTextCursor.Document)
        cursor.mergeBlockFormat(block)
        if self.chart:
            self.read_layout.removeWidget(self.chart)
            self.chart.deleteLater()
            self.chart = None
        charts = self.record.get("charts", []) if self.record else []
        if charts:
            self.chart = Chart(charts[0], self.settings)
            self.read_layout.addWidget(self.chart)

    def toggle_preview(self):
        if self.stack.currentIndex() == 0:
            self.update_preview()
        self.stack.setCurrentIndex(1 - self.stack.currentIndex())
        editing = self.stack.currentIndex() == 0 and not self.record.get("deleted")
        self.toolbar_widget.setVisible(editing)
        self.tags.setVisible(editing)
        self.preview_button.setText("编辑" if self.stack.currentIndex() else "预览")

    def show_sources(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("来源与覆盖情况")
        dialog.resize(760, 600)
        layout = QVBoxLayout(dialog)
        view = QTextBrowser()
        lines = []
        for source in self.record.get("sources", []):
            lines.append(f"## {source['title']}\n\n{source.get('at') or '日期未知'} · {source.get('origin', '')}\n\n{source.get('excerpt', '')}\n")
        warnings = self.record.get("provenance", {}).get("warnings", [])
        view.setPlainText("\n".join([*warnings, *lines]) or "这篇记录没有生成来源。")
        layout.addWidget(view)
        dialog.exec()

    def history(self):
        if not self.record or not self.record.get("id") or not self.save():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("历史版本")
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        versions = QListWidget()
        for version in self.record["versions"]:
            versions.addItem(version["at"][:19] + "  " + version["title"])
        text = QTextBrowser()
        versions.currentRowChanged.connect(lambda row: text.setPlainText(self.library.version(self.record["id"], row)["body"]) if row >= 0 else None)
        layout.addWidget(versions)
        layout.addWidget(text, 1)
        button = QPushButton("将选中版本恢复为新版本")
        def recover():
            row = versions.currentRow()
            if row >= 0:
                try:
                    saved = self.library.save(self.library.version(self.record["id"], row), self.record["id"], self.record["hash"])
                    self.load(saved)
                    self.saved.emit(saved["id"])
                    dialog.accept()
                except (DiaryError, OSError) as error:
                    QMessageBox.warning(dialog, "恢复失败", str(error))
        button.clicked.connect(recover)
        layout.addWidget(button)
        versions.setCurrentRow(max(0, versions.count() - 1))
        dialog.exec()

    def delete(self):
        if not self.record.get("id") or not self.save():
            return
        entry_id = self.record["id"]
        try:
            if self.record.get("deleted"):
                if QMessageBox.question(self, "永久删除", "永久删除正文和全部历史？此操作不可恢复。") != QMessageBox.Yes:
                    return
                self.library.purge(entry_id, confirmed=True)
            else:
                self.library.delete(entry_id)
            self.clear()
            self.saved.emit("")
        except (DiaryError, OSError) as error:
            self.message.setText(str(error))

    def restore_record(self):
        try:
            entry_id = self.record["id"]
            self.library.restore(entry_id)
            self.clear()
            self.saved.emit("")
        except (DiaryError, OSError) as error:
            self.message.setText(str(error))
