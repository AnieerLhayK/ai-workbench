"""Independent e-Diary entry; real mode requires external, user-owned configuration."""
import argparse
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QApplication

from ..app import create_application, WindowInstance
from .codex import CodexAdapter, DemoAdapter
from .cycles import Cycles
from .jobs import GenerationJobs
from .library import DiaryLibrary, DiaryError, load_json
from .reports import Reports
from .settings import Settings
from .sources import Sources
from .window import DiaryWindow


def demo_library():
    library = DiaryLibrary()
    for offset, title, body in (
        (0, "留一点时间给自己", "今天把几件拖着的小事做完了。忙的时候总觉得一天很短，停下来才发现，真正让我疲惫的并不是事情本身，而是一直惦记着它们。\n\n傍晚出去走了一会儿，没有特意想什么。回来的路上，忽然觉得今天也有值得留下的部分。\n\n先记到这里。明天的事，明天再说。"),
        (2, "整理工作思路", "把这段时间的想法梳理了一下，感觉事情清楚了一些。"),
        (5, "秋日的傍晚", "出去走了一会儿，风有些凉。"),
        (9, "一些新的尝试", "今天试着做了一个小调整，过程比想象中顺利。"),
        (13, "十月的开始", "新的月份，想把节奏放慢一些。")):
        library.save({"kind": "diary", "date": (date.today() - timedelta(days=offset)).isoformat(),
                      "title": title, "body": body, "tags": ["日常", "随想"]})
    for kind, title in (("development", "把工具慢慢做顺手"), ("work", "这周的进展与问题"), ("personal", "这三周，慢慢找回节奏")):
        library.save({"kind": kind, "date": date.today().isoformat(), "title": title,
            "body": "这段时间，你对自己的描述逐渐从“总被事情推着走”，变成了“能留出一点时间做想做的事”。变化并不大，但在几篇日记里反复出现。\n\n前半段记录更多的是疲惫和分心。后来，即使还有没有完成的事，你也开始写下散步、休息，以及做完一件小事后的轻松。\n\n演示内容，不代表你的实际经历。",
            "period": {"start": (date.today()-timedelta(days=21)).isoformat(), "end": date.today().isoformat()},
            "charts": [{"title": "记录分布", "caption": "日记篇数，仅表示记录频率（演示）", "labels": ["第一周", "第二周", "第三周"], "values": [1, 2, 2]}],
            "sources": []})
    return library


def create_window(config=None, *, demo=False):
    QApplication.instance().setStyle("Fusion")
    config = dict(config or {})
    config["demo"] = demo
    if demo:
        config["read_codex"] = False
        config["source_roots"] = []
        library = demo_library()
    else:
        root = config.get("data_root")
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise DiaryError("配置 data_root 必须为外部数据目录的绝对路径")
        library = DiaryLibrary(root)
    settings = Settings(library.root, config)
    config.update(settings.data.get("runtime", {}))
    if not demo:
        settings.update()  # Persist the first-run anchor once, not on each launch.
    sources = Sources(settings, library, config)
    cycles, reports = Cycles(settings), Reports(settings)
    adapter = DemoAdapter() if demo else CodexAdapter(config)
    jobs = GenerationJobs(adapter, sources, library, settings, reports, cycles, config)
    return DiaryWindow(library, settings, sources, jobs, reports, cycles, config)


def main(argv=None):
    parser = argparse.ArgumentParser(description="e-Diary：日记、工作记录与个人回顾")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config", type=Path)
    group.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)
    app = create_application()
    app.setApplicationName("e-Diary")
    instance = None
    try:
        config = {} if args.demo else load_json(args.config)
        if not isinstance(config, dict):
            raise DiaryError("无法读取 e-Diary 配置")
        root = None if args.demo else Path(config["data_root"]).resolve()
        instance = WindowInstance("e-diary:" + str(root or "demo"), root / "gui.lock" if root else None)
        if instance.already_running:
            return 0
        window = create_window(config, demo=args.demo)
        instance.attach(window)
        window.show()
        return app.exec()
    except Exception as error:
        QMessageBox.critical(None, "e-Diary 无法启动", str(error))
        return 1
    finally:
        if instance:
            instance.server.close()
            if instance.lock: instance.lock.close()
