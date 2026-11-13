"""Render the owned vector mark into a Windows multi-resolution icon.

Every frame is rendered at its exact pixel size into a square canvas; a
non-square mark (muti-ai) is aspect-fit and centred.  Windows rejects icon
files whose directory entry size does not match the embedded image, so the
size must never come from Qt's device-pixel-ratio scaling.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[1] / "src/ai_workbench/assets"
ICONS = ("muti-ai", "experiment-box", "e-diary", "e-chatter")
SIZES = (16, 24, 32, 48, 64, 128, 256)
PNG_FRAME_SIZE = 256


def render_frame(svg_path: Path, size: int) -> QImage:
    """Render one icon frame at exactly ``size`` x ``size`` pixels."""
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG: {svg_path}")
    source = renderer.defaultSize()
    if not source.isValid() or source.width() <= 0 or source.height() <= 0:
        raise ValueError(f"SVG has no intrinsic size: {svg_path}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale = min(size / source.width(), size / source.height())
        width, height = source.width() * scale, source.height() * scale
        target = QRectF((size - width) / 2, (size - height) / 2, width, height)
        renderer.render(painter, target)
    finally:
        painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def bmp_bytes(image: QImage) -> bytes:
    """Encode a 32-bpp DIB frame plus the trailing AND mask used by ICO."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    bits = bytes(image.constBits())
    stride = image.bytesPerLine()
    xor = b"".join(
        bits[row * stride:row * stride + width * 4] for row in reversed(range(height))
    )
    mask_stride = ((width + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * height)
    header = struct.pack(
        "<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(xor) + len(mask), 0, 0, 0, 0
    )
    return header + xor + mask


def build_icon(svg_path: Path, ico_path: Path) -> None:
    """Write a shell-loadable ICO whose frames and directory entries agree."""
    svg_path, ico_path = Path(svg_path), Path(ico_path)
    frames = []
    for size in SIZES:
        image = render_frame(svg_path, size)
        frames.append((size, png_bytes(image) if size == PNG_FRAME_SIZE else bmp_bytes(image)))
    offset = 6 + 16 * len(frames)
    entries = bytearray()
    payload = bytearray()
    for size, data in frames:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    ico_path.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + bytes(entries) + bytes(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        choices=ICONS,
        default="muti-ai",
    )
    args = parser.parse_args()
    ico_path = ASSETS / f"{args.name}.ico"
    build_icon(ASSETS / f"{args.name}.svg", ico_path)
    print(f"Wrote {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
