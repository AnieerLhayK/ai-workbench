"""muti-ai native controls; presentation observes independent Modules."""
import argparse
import hashlib
import sys
from pathlib import Path
from PySide6.QtCore import QLibraryInfo, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget
from .catalog import CATEGORIES, SERVICE_LAUNCHERS, TERMINAL_LAUNCHERS, expanded_categories
from .demo import DemoAdapter
from .lifecycle import Controller, Phase, State
from .storage import ProcessLock, atomic_json, load_config, read_json
from .terminal import DemoTerminalAdapter, TerminalLauncher, WindowsTerminalAdapter, project_path, recent_projects, remember_project

ASSETS = Path(__file__).resolve().parent / "assets"
STATUS = {Phase.CHECKING: "正在检查…", Phase.UNKNOWN: "状态未确认", Phase.STOPPED: "已停止", Phase.STARTING: "启动中…", Phase.RUNNING: "运行中", Phase.STOPPING: "停止中…", Phase.FAILED: "操作失败"}
PALETTES = {
    "dark": dict(bg="#171c24", bar="#14181f", text="#e8edf5", muted="#98a4b5", line="#2b3442", off="#4b5668", accent="#6599dc", error="#f08b91", hover="#273243"),
    "light": dict(bg="#ffffff", bar="#f8fafc", text="#202832", muted="#697586", line="#dde4ec", off="#bac2ce", accent="#518cd3", error="#b32734", hover="#e8eff8"),
}

def create_application():
    existing = QApplication.instance()
    if existing is not None:
        return existing
    platforms = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "platforms"
    app = QApplication([sys.argv[0], "-platformpluginpath", str(platforms)])
    app.setApplicationName("muti-ai")
    app.setWindowIcon(QIcon(str(ASSETS / "muti-ai.svg")))
    return app

class Switch(QAbstractButton):
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(56, 32)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.colors = PALETTES["dark"]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(1 if self.isEnabled() else 0.55)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.colors["accent"] if self.isChecked() else self.colors["off"]))
        p.drawRoundedRect(QRectF(1, 1, 54, 30), 15, 15)
        p.setBrush(QColor("#f5f8fc"))
        p.drawEllipse(QRectF(27 if self.isChecked() else 5, 5, 22, 22))
        if self.hasFocus():
            p.setPen(QPen(QColor(self.colors["accent"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0, 0, 55, 31), 15, 15)

class StatusMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self.pending, self.color, self.angle = False, "#98a4b5", 0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.advance)

    def advance(self):
        self.angle = (self.angle + 18) % 360
        self.update()

    def set_indicator(self, pending, color):
        self.pending, self.color = pending, color
        self.timer.start() if pending else self.timer.stop()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.pending:
            p.setPen(QPen(QColor(self.color), 2))
            p.drawArc(QRectF(2, 2, 12, 12), self.angle * 16, 270 * 16)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.color))
            p.drawEllipse(QRectF(3, 3, 10, 10))

class ControlRow(QWidget):
    def __init__(self, title, controller):
        super().__init__()
        self.controller, self.colors = controller, PALETTES["dark"]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 14)
        layout.setSpacing(24)
        labels = QVBoxLayout()
        labels.setSpacing(8)
        labels.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.heading = QLabel(title)
        self.heading.setObjectName("toolHeading")
        self.heading.setWordWrap(True)
        labels.addWidget(self.heading)
        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        self.mark, self.status = StatusMark(), QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        status_layout.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignVCenter)
        status_layout.addWidget(self.status, 1)
        labels.addLayout(status_layout)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        labels.addWidget(self.error)
        layout.addLayout(labels, 1)
        self.toggle = Switch()
        self.toggle.setAccessibleName(title + " 开关")
        self.toggle.clicked.connect(lambda checked: controller.start() if checked else controller.stop())
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        self.unsubscribe = controller.observe(self.render)

    def render(self, state):
        self.status.setText(state.detail or STATUS[state.phase])
        self.toggle.setChecked(state.running)
        self.toggle.setEnabled(state.available)
        self.toggle.setToolTip("关闭" if state.running else "开启")
        pending = state.pending or state.phase == Phase.CHECKING
        self.mark.set_indicator(pending, self.colors["accent"] if state.running or pending else self.colors["muted"])
        self.error.setText(state.error or "")
        self.error.setVisible(bool(state.error))
        self.toggle.update()

class CategoryHeader(QPushButton):
    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
        else:
            super().keyPressEvent(event)


class TerminalRow(QWidget):
    def __init__(self, launcher, controller):
        super().__init__()
        self.launcher, self.controller = launcher, controller
        self.project = ""
        self.colors = PALETTES["dark"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 14)
        self.heading = QLabel(launcher.title)
        self.heading.setObjectName("toolHeading")
        layout.addWidget(self.heading)
        line = QHBoxLayout()
        self.mark, self.status = StatusMark(), QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        line.addWidget(self.mark)
        line.addWidget(self.status, 1)
        layout.addLayout(line)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.buttons = {}
        for mode, title in (("new", "新建会话"), ("resume", "恢复最近会话")):
            button = QPushButton(title)
            button.setObjectName("launchButton")
            button.setAccessibleName(launcher.title + " " + title)
            button.clicked.connect(lambda checked=False, selected=mode: controller.launch(launcher.id, self.project, selected))
            self.buttons[mode] = button
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.unsubscribe = controller.observe(self.render)

    def set_project(self, project):
        self.project = project
        self.render(self.controller.state)

    def render(self, state):
        try:
            project_path(self.project)
            valid = True
        except ValueError:
            valid = False
        for button in self.buttons.values():
            button.setEnabled(valid and not state.pending)
        text = "正在打开终端…" if state.pending else "已打开终端" if state.dispatched else "派发失败" if state.error else "请选择有效的项目目录" if not valid else "就绪 · 终端内确认会话状态"
        if state.project:
            text += "\n" + state.project
        self.status.setText(text)
        self.error.setText(state.error or "")
        self.error.setVisible(bool(state.error))
        self.mark.set_indicator(state.pending, self.colors["accent"] if state.pending or state.dispatched else self.colors["muted"])


class CategoryGroup(QWidget):
    """Collapse presentation only; state observation remains active when hidden."""
    def __init__(self, category, rows, expanded):
        super().__init__()
        self.category, self.rows = category, rows
        self.colors = PALETTES["dark"]
        self.setObjectName("categoryGroup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.header = CategoryHeader()
        self.header.setObjectName("categoryHeader")
        self.header.setMinimumHeight(48)
        self.header.setCheckable(True)
        self.header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.header.setAccessibleName(category.title + " 分类")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(10)
        self.arrow = QLabel()
        title = QLabel(category.title)
        title.setObjectName("categoryTitle")
        self.mark, self.summary = StatusMark(), QLabel("暂无启动器")
        self.summary.setObjectName("categorySummary")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self.arrow)
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.mark)
        header_layout.addWidget(self.summary, 1)
        for widget in (self.arrow, title, self.mark, self.summary):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.header)
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(24, 0, 14, 8)
        if rows:
            for row in rows:
                body_layout.addWidget(row)
        else:
            self.empty = QLabel("暂无启动器")
            self.empty.setObjectName("emptyCategory")
            self.empty.setContentsMargins(0, 10, 0, 10)
            body_layout.addWidget(self.empty)
        layout.addWidget(self.body)
        self.header.toggled.connect(self.set_expanded)
        self.header.setChecked(expanded)
        self.set_expanded(expanded)
        if rows:
            self.unsubscribes = [row.controller.observe(lambda state: self.render()) for row in rows]
        else:
            self.mark.hide()

    def set_expanded(self, expanded):
        self.body.setVisible(expanded)
        self.arrow.setText("▾" if expanded else "▸")
        self.header.setAccessibleDescription("已展开" if expanded else "已收起")

    def render(self):
        states = [row.controller.state for row in self.rows]
        errors = [state.error for state in states if state.error]
        pending = any(state.pending or isinstance(state, State) and state.phase == Phase.CHECKING for state in states)
        running = any(isinstance(state, State) and state.running for state in states)
        if len(states) == 1 and isinstance(states[0], State):
            detail = states[0].detail or STATUS[states[0].phase]
        else:
            detail = "正在打开终端…" if pending else f"{sum(len(row.buttons) if isinstance(row, TerminalRow) else 1 for row in self.rows)} 个启动操作"
        self.summary.setText(detail + (" · 有错误" if errors else ""))
        self.header.setToolTip("\n".join(errors) if errors else detail)
        color = self.colors["error"] if errors else self.colors["accent"] if running or pending else self.colors["muted"]
        self.mark.set_indicator(pending, color)


class CaptionButton(QPushButton):
    def __init__(self, kind):
        super().__init__()
        self.kind, self.color = kind, "#e8edf5"
        self.setFixedSize(40, 36)
        self.setAccessibleName({"minimize": "最小化", "maximize": "最大化", "close": "关闭窗口"}[kind])

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(self.color), 1.4))
        if self.kind == "minimize": p.drawLine(15, 18, 25, 18)
        elif self.kind == "maximize": p.drawRect(15, 13, 10, 10)
        else:
            p.drawLine(15, 13, 25, 23)
            p.drawLine(25, 13, 15, 23)

class TitleBar(QWidget):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        w = self.window()
        w.showNormal() if w.isMaximized() else w.showMaximized()

class Workbench(QMainWindow):
    def __init__(self, controllers=None, preferences=None, demo=False, terminal_launchers=None):
        super().__init__()
        self.setWindowTitle("muti-ai")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.resize(760, 440)
        self.setMinimumSize(620, 380)
        self.preferences = preferences
        preference_values = read_json(preferences) if preferences else {}
        self.theme = preference_values.get("theme", "dark")
        if not isinstance(self.theme, str) or self.theme not in PALETTES: self.theme = "dark"
        expanded = expanded_categories(preference_values)
        root = QWidget()
        root.setObjectName("shell")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        bar = TitleBar()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(56)
        header = QHBoxLayout(bar)
        header.setContentsMargins(24, 6, 8, 6)
        self.brand = QLabel()
        header.addWidget(self.brand)
        name = QLabel("muti-ai")
        name.setObjectName("brandName")
        header.addWidget(name)
        header.addStretch()
        self.settings = QToolButton()
        self.settings.setAccessibleName("设置")
        self.settings.setToolTip("设置")
        self.settings.setFixedSize(36, 36)
        self.settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu, self.theme_actions = QMenu(self), {}
        for theme, title in (("dark", "深色模式"), ("light", "浅色模式")):
            action = QAction(title, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, selected=theme: self.set_theme(selected))
            self.menu.addAction(action)
            self.theme_actions[theme] = action
        self.settings.setMenu(self.menu)
        header.addWidget(self.settings)
        self.caption_buttons = [CaptionButton(kind) for kind in ("minimize", "maximize", "close")]
        self.caption_buttons[0].clicked.connect(self.showMinimized)
        self.caption_buttons[1].clicked.connect(lambda: self.showNormal() if self.isMaximized() else self.showMaximized())
        self.caption_buttons[2].clicked.connect(self.close)
        for button in self.caption_buttons: header.addWidget(button)
        outer.addWidget(bar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 12, 24, 18)
        layout.setSpacing(12)
        self.recent_projects = recent_projects(preference_values.get("recent_projects"))
        self.project = preference_values.get("selected_project", "")
        if not isinstance(self.project, str): self.project = ""
        project_line = QHBoxLayout()
        project_line.addWidget(QLabel("项目"))
        self.project_selector = QComboBox()
        self.project_selector.setAccessibleName("当前项目与最近项目")
        self.project_selector.setMinimumWidth(0)
        self.project_selector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.choose_project = QPushButton("选择文件夹")
        self.choose_project.setObjectName("launchButton")
        self.choose_project.clicked.connect(self.browse_project)
        project_line.addWidget(self.project_selector, 1)
        project_line.addWidget(self.choose_project)
        layout.addLayout(project_line)
        self.project_hint = QLabel()
        self.project_hint.setObjectName("status")
        self.project_hint.setWordWrap(True)
        layout.addWidget(self.project_hint)
        self.adapters = {}
        if controllers is None:
            if not demo: raise ValueError("真实模式必须提供本机控制配置")
            self.adapters = {launcher.id: DemoAdapter(self) for launcher in SERVICE_LAUNCHERS}
            controllers = {key: Controller(adapter) for key, adapter in self.adapters.items()}
        self.rows = {launcher.id: ControlRow(launcher.title, controllers[launcher.id]) for launcher in SERVICE_LAUNCHERS}
        if terminal_launchers is None:
            terminal_launchers = {launcher.id: TerminalLauncher(DemoTerminalAdapter(self) if demo else WindowsTerminalAdapter({}, self)) for launcher in TERMINAL_LAUNCHERS}
        self.terminal_rows = {launcher.id: TerminalRow(launcher, terminal_launchers[launcher.id]) for launcher in TERMINAL_LAUNCHERS}
        self.refresh_projects()
        self.project_selector.activated.connect(self.activate_project)
        self.update_project_rows()
        self.scroll = QScrollArea()
        self.scroll.setObjectName("categoriesScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        groups_widget = QWidget()
        groups_layout = QVBoxLayout(groups_widget)
        groups_layout.setContentsMargins(0, 0, 8, 0)
        groups_layout.setSpacing(8)
        self.groups = {}
        for category in CATEGORIES:
            rows = tuple((self.rows if launcher.kind == "service" else self.terminal_rows)[launcher.id] for launcher in category.launchers)
            group = CategoryGroup(category, rows, category.id in expanded)
            group.header.toggled.connect(self.save_expansion)
            self.groups[category.id] = group
            groups_layout.addWidget(group)
        groups_layout.addStretch()
        self.scroll.setWidget(groups_widget)
        layout.addWidget(self.scroll, 1)
        self.footer = QLabel("模拟演示 · 不操作真实服务" if demo else "分别控制，互不影响")
        self.footer.setObjectName("footer")
        layout.addWidget(self.footer)
        outer.addWidget(content, 1)
        root.setMouseTracking(True)
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            child.installEventFilter(self)
        self.set_theme(self.theme, persist=False)

    def refresh_projects(self):
        self.project_selector.clear()
        self.project_selector.addItem("请选择项目目录", "")
        values = recent_projects(([self.project] if self.project else []) + self.recent_projects)
        for value in values:
            self.project_selector.addItem(value, value)
        self.project_selector.setCurrentIndex(max(0, self.project_selector.findData(self.project)))
        self.project_selector.setToolTip(self.project)

    def browse_project(self):
        selected = QFileDialog.getExistingDirectory(self, "选择项目目录", self.project if Path(self.project).is_dir() else "")
        if selected: self.select_project(selected)

    def activate_project(self, index):
        self.select_project(self.project_selector.itemData(index))

    def select_project(self, value):
        self.project = value
        if value:
            self.recent_projects = remember_project(value, self.recent_projects)
        self.save_preferences(selected_project=value, recent_projects=self.recent_projects)
        self.refresh_projects()
        self.update_project_rows()

    def update_project_rows(self):
        for row in self.terminal_rows.values(): row.set_project(self.project)
        try:
            project_path(self.project)
            hint = "终端入口使用此目录；已打开的会话保持原目录"
        except ValueError:
            hint = "目录不存在，请重新选择" if self.project else "先选择项目，再打开 Codex 或 Claude"
        self.project_hint.setText(hint)

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            pos = watched.mapTo(self, event.position().toPoint())
            edges = Qt.Edge(0)
            if pos.x() < 6: edges |= Qt.Edge.LeftEdge
            if pos.x() > self.width() - 6: edges |= Qt.Edge.RightEdge
            if pos.y() < 6: edges |= Qt.Edge.TopEdge
            if pos.y() > self.height() - 6: edges |= Qt.Edge.BottomEdge
            if edges:
                self.windowHandle().startSystemResize(edges)
                return True
        return super().eventFilter(watched, event)

    def set_theme(self, theme, persist=True):
        c, self.theme = PALETTES[theme], theme
        if persist: self.save_preferences(theme=theme)
        for name, action in self.theme_actions.items(): action.setChecked(name == theme)
        self.brand.setPixmap(QIcon(str(ASSETS / ("muti-ai.svg" if theme == "dark" else "muti-ai-light.svg"))).pixmap(32, 24))
        self.settings.setIcon(QIcon(str(ASSETS / ("settings.svg" if theme == "dark" else "settings-light.svg"))))
        for button in self.caption_buttons:
            button.color = c["text"]
            button.update()
        for row in self.rows.values():
            row.colors = row.toggle.colors = c
            row.render(row.controller.state)
        for row in self.terminal_rows.values():
            row.colors = c
            row.render(row.controller.state)
        for group in self.groups.values():
            group.colors = c
            if group.rows: group.render()
        self.setStyleSheet(f"""
            QWidget {{ color: {c['text']}; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; background: {c['bg']}; }}
            QWidget#shell {{ border: 1px solid {c['line']}; }}
            QWidget#titlebar, QWidget#titlebar QLabel {{ background: {c['bar']}; }}
            QLabel#brandName {{ font-size: 24px; font-weight: 600; }}
            QLabel#toolHeading {{ font-size: 18px; font-weight: 600; }}
            QLabel#status, QLabel#footer {{ color: {c['muted']}; }}
            QLabel#error {{ color: {c['error']}; font-size: 12px; }}
            QWidget#categoryGroup {{ border: 1px solid {c['line']}; border-radius: 6px; }}
            QPushButton#categoryHeader {{ border: 1px solid transparent; text-align: left; }}
            QPushButton#categoryHeader:focus {{ border: 1px solid {c['accent']}; }}
            QPushButton#categoryHeader QLabel {{ background: transparent; }}
            QLabel#categoryTitle {{ font-size: 15px; font-weight: 600; }}
            QLabel#categorySummary, QLabel#emptyCategory {{ color: {c['muted']}; }}
            QScrollArea#categoriesScroll {{ border: none; }}
            QScrollBar:vertical {{ background: {c['bg']}; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {c['off']}; min-height: 24px; border-radius: 4px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QPushButton, QToolButton {{ border: none; background: transparent; border-radius: 4px; }}
            QPushButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
            QPushButton#launchButton {{ border: 1px solid {c['line']}; padding: 7px 12px; }}
            QPushButton#launchButton:focus, QComboBox:focus {{ border: 1px solid {c['accent']}; }}
            QPushButton:disabled {{ color: {c['muted']}; }}
            QComboBox {{ border: 1px solid {c['line']}; padding: 7px; }}
            QToolButton::menu-indicator {{ image: none; }}
            QMenu {{ padding: 8px; border: 1px solid {c['line']}; }}
            QMenu::item {{ padding: 8px 16px; }}
            QMenu::item:selected {{ background: {c['hover']}; }}
        """)

    def save_preferences(self, **changes):
        if self.preferences:
            values = read_json(self.preferences)
            values.update(changes)
            atomic_json(self.preferences, values)

    def save_expansion(self):
        self.save_preferences(expanded_categories=[key for key, group in self.groups.items() if group.header.isChecked()])

class WindowInstance:
    def __init__(self, key, lock_path=None):
        self.name = "muti-ai-" + hashlib.sha256(key.encode()).hexdigest()[:24]
        self.server, self.socket = QLocalServer(), QLocalSocket()
        self.lock = ProcessLock(lock_path) if lock_path else None
        self.socket.connectToServer(self.name)
        self.already_running = self.socket.waitForConnected(400)
        if self.lock and not self.lock.acquired and not self.already_running:
            import time
            for attempt in range(25):
                self.socket.abort()
                self.socket.connectToServer(self.name)
                if self.socket.waitForConnected(100):
                    self.already_running = True
                    break
                time.sleep(0.1)
            if not self.already_running:
                raise RuntimeError("已有窗口正在启动，请稍后再次打开")
        if self.already_running:
            self.socket.write(b"show")
            self.socket.waitForBytesWritten(400)
            self.socket.disconnectFromServer()
        else:
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name): raise RuntimeError("无法创建窗口单实例入口")

    def attach(self, window):
        def activate():
            socket = self.server.nextPendingConnection()
            if socket:
                socket.disconnectFromServer()
                socket.deleteLater()
            window.showNormal()
            window.raise_()
            window.activateWindow()
        self.server.newConnection.connect(activate)

def main(argv=None):
    parser = argparse.ArgumentParser(description="muti-ai local native controls")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)
    app = create_application()
    try:
        config = None if args.demo else load_config(args.config) if args.config else None
        if not args.demo and config is None: raise ValueError("未配置本机控制入口；开发演示请显式使用 --demo")
        instance = WindowInstance(str(Path(config["data_root"]).resolve()) if config else "demo", Path(config["data_root"]) / "gui.lock" if config else None)
        if instance.already_running: return 0
        if args.demo:
            window = Workbench(demo=True)
        else:
            from .local import LocalAdapter
            adapters = {launcher.id: LocalAdapter(launcher.id, config, args.config) for launcher in SERVICE_LAUNCHERS}
            controllers = {key: Controller(adapter) for key, adapter in adapters.items()}
            terminals = {launcher.id: TerminalLauncher(WindowsTerminalAdapter(config, app)) for launcher in TERMINAL_LAUNCHERS}
            window = Workbench(controllers, Path(config["data_root"]) / "preferences.json", terminal_launchers=terminals)
            window.adapters = adapters
        instance.attach(window)
        window.show()
        try:
            return app.exec()
        finally:
            instance.server.close()
            if instance.lock:
                instance.lock.close()
    except Exception as error:
        QMessageBox.critical(None, "muti-ai 无法启动", str(error))
        return 1
