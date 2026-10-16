"""Independent desktop entry point; external config selects all host paths."""
import argparse
import json
from pathlib import Path
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox

from ..app import create_application, WindowInstance
from ..terminal import DemoTerminalAdapter, WindowsTerminalAdapter
from .launch import ExperimentLauncher, command_argv
from .model import TrialStore, demo_store
from .window import ExperimentWindow
from .service import ExperimentService

ICON = Path(__file__).resolve().parents[1] / "assets" / "experiment-box.svg"


def load_config(path):
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict) or not isinstance(config.get("data_root"), str) or not Path(config["data_root"]).is_absolute():
            raise ValueError("本机数据目录必须为绝对路径")
        # Missing executable paths affect launch only; card editing remains usable.
        return config
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("个人试验盒配置无法读取，请检查桌面入口使用的配置文件") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description="个人试验盒：手动试验与继续记录")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config", type=Path)
    group.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)
    app = create_application()
    app.setApplicationName("个人试验盒")
    app.setWindowIcon(QIcon(str(ICON)))
    try:
        config = None if args.demo else load_config(args.config)
        root = Path(config["data_root"]).resolve() if config else None
        instance = WindowInstance("experiment-box:" + str(root or "demo"), root / "gui.lock" if root else None)
        if instance.already_running:
            if instance.lock:
                instance.lock.close()
            return 0
        try:
            store = demo_store() if args.demo else TrialStore(root / "trials.json")
            adapter = DemoTerminalAdapter(app) if args.demo else WindowsTerminalAdapter(config, app, command_builder=command_argv)
            launcher = ExperimentLauncher(adapter)
            service = ExperimentService(store, root)
            window = ExperimentWindow(service, launcher, demo=args.demo, config=config, config_path=args.config)
            instance.attach(window)
            window.show()
            if sys.platform == "win32":
                import ctypes
                enabled = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(int(window.winId()), 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
            return app.exec()
        finally:
            instance.server.close()
            if instance.lock:
                instance.lock.close()
    except Exception as error:
        QMessageBox.critical(None, "个人试验盒无法启动", str(error))
        return 1
