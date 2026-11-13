"""Owned Windows icons must be loadable by the shell: exact, square frames.

Windows silently falls back to the generic shortcut icon when an ICO directory
entry disagrees with the embedded image.  Keep the artifact contract and the
build-time encoder covered by the same seam.
"""
from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/ai_workbench/assets"

_SPEC = importlib.util.spec_from_file_location("make_icon", ROOT / "scripts/make_icon.py")
make_icon = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(make_icon)


def read_frames(path: Path) -> list[tuple[int, str]]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1), f"not an ICO: {path.name}"
    assert count == len(make_icon.SIZES), f"{path.name}: {count} frames"
    frames = []
    for index in range(count):
        base = 6 + 16 * index
        width, height = data[base], data[base + 1]
        width = 256 if width == 0 else width
        height = 256 if height == 0 else height
        planes, depth = struct.unpack_from("<HH", data, base + 4)
        size, offset = struct.unpack_from("<II", data, base + 8)
        assert (planes, depth) == (1, 32), f"{path.name}: frame {index} is not 32-bpp"
        frame = data[offset:offset + size]
        assert len(frame) == size, f"{path.name}: frame {index} is truncated"
        if frame.startswith(b"\x89PNG\r\n\x1a\n"):
            image_kind = "png"
            image_width, image_height = struct.unpack_from(">II", frame, 16)
        else:
            image_kind = "bmp"
            header = struct.unpack_from("<IiiHHIIiiII", frame, 0)
            assert header[0] == 40, f"{path.name}: frame {index} is not a DIB"
            image_width, image_height = header[1], header[2] // 2
            assert header[3:5] == (1, 32)
        assert (image_width, image_height) == (width, height), (
            f"{path.name}: frame {index} declares {width}x{height} but embeds "
            f"{image_width}x{image_height}"
        )
        assert width == height, f"{path.name}: frame {index} is not square"
        frames.append((width, image_kind))
    return frames


def expected_frames() -> list[tuple[int, str]]:
    return [(size, "png" if size == make_icon.PNG_FRAME_SIZE else "bmp") for size in make_icon.SIZES]


def test_committed_icons_have_exact_square_frames():
    for name in make_icon.ICONS:
        assert read_frames(ASSETS / f"{name}.ico") == expected_frames(), name


def test_generator_emits_exact_square_frames(tmp_path):
    output = tmp_path / "icon.ico"
    make_icon.build_icon(ASSETS / "muti-ai.svg", output)
    assert read_frames(output) == expected_frames()


def test_installers_point_shortcuts_at_deployed_copies():
    installers = {
        "Install-EDiary.ps1": "e-diary.ico",
        "Install-ExperimentBox.ps1": "experiment-box.ico",
        "Install-Local.ps1": "muti-ai.ico",
    }
    assert (ROOT / "scripts/Copy-ShortcutIcon.ps1").is_file()
    for name, icon in installers.items():
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert ". (Join-Path $PSScriptRoot 'Copy-ShortcutIcon.ps1')" in text, name
        assert "$iconPath = Copy-ShortcutIcon" in text, name
        assert f"Join-Path $DataRoot '{icon}'" in text, name
        assert "$shortcut.IconLocation = $iconPath + ',0'" in text, name
        assert "IconLocation = (Join-Path $packageRoot" not in text, name
