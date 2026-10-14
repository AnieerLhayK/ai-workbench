"""Native application shell; composition glue for the diary's deep Modules."""
from datetime import date, datetime, timedelta

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QRect
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QListWidget, QListWidgetItem, QStackedWidget,
    QSplitter, QMessageBox, QFrame, QStyledItemDelegate, QStyleOptionViewItem, QStyle)
from PySide6.QtGui import QGuiApplication, QFont, QColor

from .editor import Editor
from .library import DiaryError, KINDS, period_label
from .pages import Preferences, CyclePage, SourcePage, ReportPage, heading, period_request
from .style import stylesheet, icon, is_dark
from ..app import PALETTES


class EntryDelegate(QStyledItemDelegate):
    def __init__(self, settings, parent):
        super().__init__(parent)
        self.settings = settings

    def sizeHint(self, option, index):
        return QSize(240, 112)

    def paint(self, painter, option, index):
        lines = index.data(Qt.DisplayRole).split("\n", 2)
        painter.save()
        painter.setClipRect(option.rect)
        dark = is_dark(self.settings.data["theme"])
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect.adjusted(0, 2, 0, -2), QColor("#293e58" if dark else "#dcebf5"))
        for row, line in enumerate(lines):
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(17 if row == 1 else 14)
            font.setWeight(QFont.DemiBold if row == 1 else QFont.Normal)
            painter.setFont(font)
            painter.setPen(QColor("#edf1f7" if dark else "#202934") if row == 1 else QColor("#a6b1c1" if dark else "#6d7989"))
            rectangle = QRect(option.rect.x() + 12, option.rect.y() + 12 + row * 29, option.rect.width() - 24, 26)
            painter.drawText(rectangle, Qt.AlignVCenter | Qt.AlignLeft, painter.fontMetrics().elidedText(line, Qt.ElideRight, rectangle.width()))
        painter.restore()


class DiaryWindow(QMainWindow):
    def __init__(self, library, settings, sources, jobs, reports, cycles, config):
        super().__init__()
        self.library, self.settings, self.sources = library, settings, sources
        self.jobs, self.reports, self.cycles, self.config = jobs, reports, cycles, config
        self.kind, self.closing = "diary", False
        self.setWindowTitle("e-Diary" + (" · 演示" if config.get("demo") else ""))
        self.setWindowIcon(icon("diary"))
        self.resize(1536, 1024)
        self.setMinimumSize(1000, 680)
        outer = QWidget()
        self.setCentralWidget(outer)
        layout = QHBoxLayout(outer)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rail = QWidget()
        self.rail.setObjectName("rail")
        self.rail.setFixedWidth(239)
        nav = QVBoxLayout(self.rail)
        nav.setContentsMargins(16, 18, 16, 18)
        nav.setSpacing(7)
        brand = QLabel("e-Diary")
        brand.setObjectName("brand")
        nav.addWidget(brand)
        new = QPushButton("＋  新建日记")
        new.setObjectName("primary")
        new.clicked.connect(self.new_entry)
        nav.addWidget(new)
        nav.addSpacing(14)
        self.navigation = {}
        for key in ("diary", "development", "work", "personal", "report"):
            if key == "personal":
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                nav.addWidget(line)
            button = QPushButton("  " + KINDS.get(key, "主题汇报"))
            button.setCheckable(True)
            button.setIconSize(QSize(23, 23))
            button.clicked.connect(lambda checked=False, k=key: self.navigate(k))
            nav.addWidget(button)
            self.navigation[key] = button
        nav.addStretch()
        for key, label in (("sources", "资料来源"), ("cycles", "周期设置"), ("trash", "回收站"), ("settings", "设置")):
            button = QPushButton("  " + label)
            button.setCheckable(True)
            button.setIconSize(QSize(23, 23))
            button.clicked.connect(lambda checked=False, k=key: self.navigate(k))
            nav.addWidget(button)
            self.navigation[key] = button
        layout.addWidget(self.rail)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.diary_page = QWidget()
        diary_layout = QVBoxLayout(self.diary_page)
        diary_layout.setContentsMargins(0, 0, 0, 0)
        diary_layout.setSpacing(0)
        splitter = QSplitter()
        self.list_panel = QWidget()
        self.list_panel.setMinimumWidth(240)
        list_layout = QVBoxLayout(self.list_panel)
        list_layout.setContentsMargins(22, 26, 22, 20)
        list_layout.setSpacing(14)
        self.list_heading = heading("日记")
        list_layout.addWidget(self.list_heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索日记")
        self.search.textChanged.connect(self.refresh_list)
        list_layout.addWidget(self.search)
        self.month = QComboBox()
        self.month.addItem("全部时间", "")
        today = date.today()
        for i in range(24):
            total = today.year * 12 + today.month - 1 - i
            year, month = divmod(total, 12)
            key = f"{year:04d}-{month+1:02d}"
            self.month.addItem(f"{year} 年 {month+1} 月", key)
        self.month.currentIndexChanged.connect(self.refresh_list)
        list_layout.addWidget(self.month)
        self.generate = QPushButton("＋ 立即生成")
        self.generate.setObjectName("primary")
        self.generate.clicked.connect(self.manual_generate)
        list_layout.addWidget(self.generate)
        self.list = QListWidget()
        self.list.setItemDelegate(EntryDelegate(settings, self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self.select_entry)
        list_layout.addWidget(self.list, 1)
        splitter.addWidget(self.list_panel)
        self.editor = Editor(library, settings)
        self.editor.saved.connect(self.entry_saved)
        self.editor.regenerate.connect(self.regenerate)
        splitter.addWidget(self.editor)
        splitter.setSizes([351, 946])
        splitter.setChildrenCollapsible(False)
        diary_layout.addWidget(splitter, 1)
        self.global_status = QLabel()
        self.global_status.setObjectName("muted")
        self.global_status.setWordWrap(True)
        self.global_status.setContentsMargins(20, 6, 20, 6)
        diary_layout.addWidget(self.global_status)
        self.pages.addWidget(self.diary_page)
        self.source_page = SourcePage(settings, sources)
        self.cycle_page = CyclePage(settings, cycles, jobs)
        self.report_page = ReportPage(reports, settings, jobs)
        self.preferences = Preferences(settings, config, self.apply_theme)
        self.extra_pages = {"sources": self.source_page, "cycles": self.cycle_page,
                            "report": self.report_page, "settings": self.preferences}
        for page in self.extra_pages.values(): self.pages.addWidget(page)
        self.apply_theme(settings.data["theme"])
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme(settings.data["theme"]))
        self.cycle_timer = QTimer(self)
        self.cycle_timer.setInterval(15000)
        self.cycle_timer.timeout.connect(self.check_cycles)
        self.cycle_timer.start()
        jobs.observe(self.job_changed)
        self.navigate("diary")

    def apply_theme(self, theme):
        if self.settings.data["theme"] != theme:
            try:
                self.settings.update(theme=theme)
            except OSError as error:
                QMessageBox.warning(self, "主题保存失败", str(error))
                return
        self.setStyleSheet(stylesheet(theme))
        color = "#bdc9dc" if is_dark(theme) else "#344254"
        for key, button in self.navigation.items():
            button.setIcon(icon(key, color))
        if hasattr(self, "cycle_page"):
            for switch, _ in self.cycle_page.controls.values():
                switch.colors = dict(PALETTES["dark" if is_dark(theme) else "light"], accent="#397eaf")
                switch.update()
        self.editor.update()

    def navigate(self, key):
        if not self.editor.save():
            return
        for kind, button in self.navigation.items(): button.setChecked(kind == key)
        if key in self.extra_pages:
            self.pages.setCurrentWidget(self.extra_pages[key])
        else:
            self.kind = key
            self.pages.setCurrentWidget(self.diary_page)
            self.list_heading.setText(KINDS.get(key, "回收站"))
            self.search.setPlaceholderText("搜索" + KINDS.get(key, "回收站"))
            self.generate.setVisible(key in ("development", "work", "personal"))
            self.editor.clear(key)
            self.refresh_list()
            if self.list.count(): self.list.setCurrentRow(0)

    def refresh_list(self, *args):
        selected_id = self.editor.record.get("id") if self.editor.record else None
        try:
            records = self.library.query(kind=None if self.kind == "trash" else self.kind,
                text=self.search.text(), month=self.month.currentData() or "", deleted=self.kind == "trash")
        except (DiaryError, OSError) as error:
            self.global_status.setText(str(error))
            return
        self.list.blockSignals(True)
        self.list.clear()
        for record in records:
            period = record.get("period")
            when = period_label(period) if period else record["date"]
            item = QListWidgetItem(when + "\n" + record["title"] + "\n" + record["body"].replace("\n", " ")[:30])
            item.setData(Qt.UserRole, record["id"])
            self.list.addItem(item)
            if record["id"] == selected_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def select_entry(self, item, previous=None):
        if not item:
            return
        entry_id = item.data(Qt.UserRole)
        if not self.editor.save():
            return
        try:
            self.editor.load(self.library.read(entry_id))
            self.list.blockSignals(True)
            for row in range(self.list.count()):
                if self.list.item(row).data(Qt.UserRole) == entry_id:
                    self.list.setCurrentRow(row)
                    break
            self.list.blockSignals(False)
        except (DiaryError, OSError) as error:
            self.global_status.setText(str(error))

    def entry_saved(self, entry_id):
        self.refresh_list()

    def new_entry(self):
        if not self.editor.save():
            return
        self.navigate("diary")
        self.editor.load({"kind": "diary", "date": date.today().isoformat(), "title": "", "body": "", "tags": [], "format": ".md"})
        self.editor.title.setFocus()

    def manual_generate(self):
        if not self.editor.save():
            return
        request = period_request(self, self.kind)
        if request:
            self.submit(request)

    def regenerate(self, record):
        if not record or not self.editor.save():
            return
        period = record.get("period")
        if not period:
            self.manual_generate()
            return
        self.submit({"kind": record["kind"], **period, "entry_id": record["id"]})

    def submit(self, request):
        try:
            self.jobs.submit(request)
        except (DiaryError, OSError) as error:
            self.global_status.setText(str(error))

    def check_cycles(self):
        if self.jobs.state["pending"] or self.config.get("demo") or self.closing:
            return
        request = self.cycles.due()
        if request:
            self.submit(request)

    def job_changed(self, state):
        self.global_status.setText(state["stage"] + ("：" + state["error"] if state.get("error") else ""))
        self.generate.setEnabled(not state["pending"])
        if not state["pending"]:
            self.refresh_list()
            if self.closing:
                QTimer.singleShot(0, self.close)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow() and hasattr(self, "editor"):
            self.editor.check_external()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "rail"):
            self.rail.setFixedWidth(180 if self.width() < 1200 else 239)

    def closeEvent(self, event):
        if not self.editor.save():
            event.ignore()
            return
        if self.jobs.state["pending"]:
            self.closing = True
            self.jobs.cancel()
            event.ignore()
            return
        self.cycle_timer.stop()
        event.accept()
