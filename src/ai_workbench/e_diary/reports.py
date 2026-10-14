"""Reports Module. Validate the whole package before publishing a unique directory."""
from collections import Counter
from datetime import date, timedelta
import html
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPdfWriter, QTextDocument
from PySide6.QtSvg import QSvgGenerator

from .library import DiaryError, atomic_text

NOTICE = "e-Diary 不具备脱敏能力，请使用其他工具处理后再展示。"
FORMATS = {".md", ".txt", ".csv", ".json", ".html", ".pdf", ".png", ".svg"}


def chart_for(bundle):
    start, end = date.fromisoformat(bundle["start"][:10]), date.fromisoformat(bundle["end"][:10])
    entries = [d for d in bundle["documents"] if d["origin"] == "diary"]
    counts = Counter(d["at"][:10] for d in entries)
    labels, values = [], []
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=7), end)
        labels.append(f"{cursor:%m.%d}–{stop - timedelta(days=1):%m.%d}")
        values.append(sum(counts[(cursor + timedelta(days=i)).isoformat()] for i in range((stop - cursor).days)))
        cursor = stop
    return {"title": "记录分布", "caption": "日记篇数，仅表示记录频率", "labels": labels,
            "values": values, "source_ids": [d["id"] for d in entries]} if entries else None


def paint_chart(device, chart, *, dark=False, width=900, height=260):
    painter = QPainter(device)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(0, 0, width, height, QColor("#1e242d" if dark else "#ffffff"))
    painter.setPen(QColor("#b5bfce" if dark else "#617080"))
    painter.setFont(QFont("Microsoft YaHei UI", 13, QFont.Bold))
    painter.drawText(QRectF(20, 8, width / 2, 26), chart["title"])
    painter.setFont(QFont("Microsoft YaHei UI", 10))
    painter.drawText(QRectF(width / 2, 8, width / 2 - 20, 26), 0x82, chart["caption"])
    values = chart["values"]
    peak = max([1, *values])
    spacing = (width - 80) / max(1, len(values))
    painter.drawLine(40, height - 42, width - 20, height - 42)
    for i, value in enumerate(values):
        x, bar_height = 45 + i * spacing, (height - 100) * value / peak
        painter.fillRect(QRectF(x, height - 43 - bar_height, spacing * .65, bar_height), QColor("#409c91"))
        painter.drawText(QRectF(x, height - 68 - bar_height, spacing * .65, 22), 0x84, str(value))
        painter.drawText(QRectF(x - 8, height - 34, spacing, 25), 0x84, chart["labels"][i])
    painter.end()


def render_chart(path, chart):
    if path.suffix == ".svg":
        from PySide6.QtCore import QSize
        device = QSvgGenerator()
        device.setFileName(str(path))
        device.setSize(QSize(900, 260))
        device.setViewBox(QRectF(0, 0, 900, 260))
    else:
        device = QImage(900, 260, QImage.Format_ARGB32)
    paint_chart(device, chart)
    if path.suffix == ".png" and not device.save(str(path)):
        raise DiaryError("图表保存失败")


def render_pdf(path, content):
    document = QTextDocument()
    document.setDefaultFont(QFont("Microsoft YaHei UI", 11))
    document.setMarkdown(content)
    writer = QPdfWriter(str(path))
    writer.setResolution(144)
    document.print_(writer)
    if not path.read_bytes().startswith(b"%PDF"):
        raise DiaryError("PDF 校验失败")


class Reports:
    def __init__(self, settings):
        self.settings = settings

    def save_topic(self, topic):
        if not all(isinstance(topic.get(k), str) and topic[k].strip() for k in ("name", "description")):
            raise DiaryError("请填写主题名称与目标边界")
        topic = dict(topic, id=topic.get("id") or uuid4().hex, prompt=topic.get("prompt", ""))
        topics = [t for t in self.settings.data["topics"] if t["id"] != topic["id"]]
        self.settings.update(topics=[*topics, topic])

    def remove_topic(self, topic_id):
        self.settings.update(topics=[t for t in self.settings.data["topics"] if t["id"] != topic_id])

    def deliver(self, result, bundle, output, job_id):
        output = Path(output)
        if not output.is_absolute() or output.is_symlink() or not output.is_dir():
            raise DiaryError("请选择存在的绝对输出目录，且不能是链接")
        package = output / ("e-Diary-" + job_id)
        temporary = output / (".e-diary-" + job_id + ".pending")
        if package.exists() or temporary.exists():
            raise DiaryError("交付目录已存在，请使用新的任务")
        proposed = result.get("files", [])
        if not isinstance(proposed, list) or len(proposed) > 20:
            raise DiaryError("材料包文件清单无效或超过 20 项，请缩小任务")
        evidence = "# 证据索引\n\n" + "\n".join(
            f"- [{d['id']}] {d['title']} · {d.get('at') or '日期未知'} · {d.get('path', d['origin'])}" for d in bundle["documents"])
        files = [{"name": "汇报正文.md", "content": "# " + result["title"] + "\n\n" + result["body"]},
                 {"name": "证据索引.md", "content": evidence}, *proposed]
        seen = set()
        for file in files:
            name, content = file.get("name", ""), file.get("content")
            if (not re.fullmatch(r"[^/\\:<>|?*\x00-\x1f]+", name) or name.startswith(".")
                    or Path(name).suffix.lower() not in FORMATS or not isinstance(content, str)
                    or len(content) > 2_000_000 or name.casefold() in seen):
                raise DiaryError("材料包含重复、越界、不支持或过大的文件")
            if Path(name).suffix.lower() == ".json":
                json.loads(content)
            seen.add(name.casefold())
        try:
            temporary.mkdir()
            for file in files:
                path = temporary / file["name"]
                extension = path.suffix.lower()
                if extension == ".pdf":
                    render_pdf(path, file["content"])
                elif extension in (".svg", ".png"):
                    chart = chart_for(bundle)
                    if not chart:
                        raise DiaryError("当前材料不足以生成可核对图表，请移除图片输出要求")
                    render_chart(path, chart)
                elif extension == ".html":
                    atomic_text(path, "<!doctype html><meta charset='utf-8'><article><pre style='white-space:pre-wrap'>" + html.escape(file["content"]) + "</pre></article>")
                else:
                    atomic_text(path, file["content"])
            atomic_text(temporary / "交付说明.txt", NOTICE + "\n\n" + "\n".join(bundle["warnings"]))
            temporary.rename(package)
        except Exception:
            if temporary.is_dir() and temporary.parent.resolve() == output.resolve():
                shutil.rmtree(temporary)
            raise
        return {"id": job_id, "title": result["title"], "path": str(package),
                "start": bundle["start"], "end": bundle["end"], "files": [f["name"] for f in files]}
