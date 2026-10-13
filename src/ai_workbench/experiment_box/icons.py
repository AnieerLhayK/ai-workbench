"""Small, consistently stroked native vector icons from the accepted concept."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    "edit": '<path d="m4 16 11-11 4 4-11 11-5 1zM13 7l4 4"/>',
    "source": '<path d="M14 4h6v6M20 4l-9 9M10 5H5v14h14v-5"/>',
    "play": '<path d="m8 5 12 7-12 7z" fill="currentColor" stroke-linejoin="round"/>',
    "record": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "folder": '<path d="M3 7V5h7l2 3h9v12H3z"/>',
}


def icon(name, color="#eef1f5"):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" color="{color}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
