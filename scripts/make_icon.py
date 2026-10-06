"""Render the owned vector mark into a Windows multi-resolution icon."""
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QIcon
from ai_workbench.app import ASSETS, create_application

if __name__ == "__main__":
    app = create_application()
    icon = QIcon(str(ASSETS / "muti-ai.svg"))
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        icon.pixmap(size, size).save(buffer, "PNG")
        images.append((size, bytes(buffer.data())))
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (ASSETS / "muti-ai.ico").write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(data for _, data in images))
