from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from ai_workbench.app import Workbench
from ai_workbench.ci.window import CIWindow, DemoCIClient


def test_muti_ai_opens_a_separate_ci_panel_and_demo_repair_is_explicit(qt_app):
    workbench = Workbench(demo=True)
    workbench.show()
    try:
        QTest.mouseClick(workbench.ci_button, Qt.MouseButton.LeftButton)
        window = workbench.ci_window
        assert window.isVisible()
        assert window.client.snapshot()["jobs"][0]["status"] == "detected"
        window.agent.setCurrentText("claude")
        window.model.setText("chosen-model")
        window.table.selectRow(0)
        QTest.mouseClick(window.repair, Qt.MouseButton.LeftButton)
        assert window.client.snapshot()["jobs"][0]["status"] == "running"
        QTest.qWait(500)
        window.refresh()
        assert window.client.snapshot()["jobs"][0]["status"] == "patch_ready"
        assert window.client.snapshot()["settings"]["agent"] == "claude"
        assert window.client.snapshot()["settings"]["model"] == "chosen-model"
        window.close()
        assert not window.timer.isActive()
        assert window.client.snapshot()["jobs"][0]["status"] == "patch_ready"
    finally:
        workbench.close()
def test_windows_command_line_preserves_paths():
    import os
    import pytest
    if os.name != "nt":
        pytest.skip("Windows command-line parsing")
    from ai_workbench.ci.window import parse_test_command
    executable = 'C' + r':\Python\python.exe'
    assert parse_test_command(executable + r' -m pytest "tests\my suite"') == [executable, '-m', 'pytest', r'tests\my suite']
