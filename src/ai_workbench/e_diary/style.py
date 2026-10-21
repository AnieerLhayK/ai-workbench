"""Shared desktop tokens. All screen families use the same chrome and typography."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from pathlib import Path

PATHS = {
    "diary": '<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6m-6 4h6"/>',
    "development": '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-12-2 18"/>',
    "work": '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V4h8v3M3 12h18m-11 0v3h4v-3"/>',
    "personal": '<path d="M5 3h14v18H5zm4 5h6m-6 4h6m-6 4h4"/>',
    "report": '<path d="M4 20V11h4v9m3 0V6h4v14m3 0V3h4v17"/>',
    "sources": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    "cycles": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    "trash": '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
    "settings": '<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3z"/><circle cx="12" cy="12" r="3"/>',
}


def icon(kind, color="#344254"):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS.get(kind, PATHS["diary"])}</svg>'
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return QIcon(pixmap)


def is_dark(mode):
    return mode == "dark" or (mode == "system" and QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)


def stylesheet(mode):
    dark = is_dark(mode)
    background, rail, text, muted, border, selected = (("#1e242d", "#181e26", "#edf1f7", "#a6b1c1", "#394453", "#293e58") if dark else
        ("#ffffff", "#f2f5f8", "#202934", "#6d7989", "#d8dfe7", "#dcebf5"))
    check = (Path(__file__).resolve().parents[1] / "assets" / "check.svg").as_posix()
    return f"""
    QWidget {{ background:{background}; color:{text}; font-family:'Microsoft YaHei UI','Segoe UI'; font-size:16px; }}
    QMainWindow {{ background:{background}; }}
    #cycleStatus {{ border-bottom:1px solid {border}; }}
    #cycleStatus QPushButton {{ padding:4px 10px; }}
    #rail {{ background:{rail}; border-right:1px solid {border}; }}
    #brand {{ font-size:24px; font-weight:600; background:transparent; padding:14px 6px 22px; }}
    #rail QPushButton {{ background:transparent; text-align:left; padding:12px 14px; border:0; font-size:19px; border-radius:6px; }}
    #rail QPushButton:checked {{ background:{selected}; color:{text}; }}
    #rail QPushButton:hover {{ background:{selected}; }}
    QPushButton {{ padding:8px 14px; border:1px solid {border}; border-radius:6px; background:{background}; }}
    QPushButton:hover {{ background:{selected}; }}
    QPushButton:disabled {{ color:{muted}; }}
    QPushButton::menu-indicator {{ image:none; width:0; }}
    QPushButton#primary, #rail QPushButton#primary {{ background:#397eaf; color:white; border:0; }}
    QLineEdit, QDateEdit, QTimeEdit, QSpinBox, QComboBox {{ border:1px solid {border}; border-radius:5px; padding:8px; selection-background-color:#397eaf; }}
    QTextEdit, QTextBrowser {{ border:1px solid {border}; border-radius:5px; padding:12px; font-size:17px; selection-background-color:#397eaf; }}
    #title {{ font-size:40px; font-weight:600; border:0; padding:14px 0; }}
    #heading {{ font-size:30px; font-weight:600; border:0; }}
    #muted {{ color:{muted}; background:transparent; }}
    #message {{ color:{'#f0c18b' if dark else '#93602d'}; padding:8px; }}
    QListWidget {{ border:0; outline:0; padding:0; }}
    QListWidget::item {{ padding:16px 10px; border-radius:6px; margin:3px 0; }}
    QListWidget::item:selected {{ background:{selected}; color:{text}; }}
    QTableWidget {{ border:1px solid {border}; gridline-color:{border}; selection-background-color:{selected}; }}
    QHeaderView::section {{ background:{rail}; border:0; padding:10px; text-align:left; }}
    QSplitter::handle {{ background:{border}; width:1px; }}
    QScrollArea {{ border:0; }}
    QCheckBox {{ spacing:8px; }}
    QCheckBox::indicator {{ width:18px; height:18px; border:1px solid {muted}; border-radius:3px; background:{background}; }}
    QCheckBox::indicator:checked {{ background:#397eaf; border:1px solid #397eaf; image:url('{check}'); }}
    QTabWidget::pane {{ border:0; }}
    QTabBar::tab {{ padding:10px 18px; border-bottom:2px solid transparent; }}
    QTabBar::tab:selected {{ border-bottom:2px solid #397eaf; color:#397eaf; }}
    QToolTip {{ background:{rail}; color:{text}; border:1px solid {border}; }}
    """
