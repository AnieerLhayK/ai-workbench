import json
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from ai_workbench.app import Workbench, WindowInstance
from ai_workbench.demo import DemoAdapter
from ai_workbench.lifecycle import Controller, Phase, State
from conftest import ControlledAdapter


def controls():
    adapters = {key: ControlledAdapter() for key in ("commander", "hermes")}
    return adapters, {key: Controller(adapter) for key, adapter in adapters.items()}


def test_initially_expanded_independent_switches_wait_failure_retry(qt_app):
    adapters, controllers = controls()
    window = Workbench(controllers)
    window.show()
    qt_app.processEvents()
    try:
        first, second = window.rows.values()
        assert first.isVisible() and second.isVisible()
        QTest.mouseClick(first.toggle, Qt.MouseButton.LeftButton)
        assert first.controller.state.phase == Phase.STARTING
        assert not first.toggle.isEnabled() and first.mark.timer.isActive()
        assert second.toggle.isEnabled()
        QTest.mouseClick(first.toggle, Qt.MouseButton.LeftButton)
        assert len(adapters["commander"].requests) == 1
        window.scroll.ensureWidgetVisible(second.toggle)
        QTest.mouseClick(second.toggle, Qt.MouseButton.LeftButton)
        adapters["hermes"].complete()
        assert second.toggle.isChecked()
        adapters["commander"].complete("模拟失败")
        assert first.error.isVisible() and not first.toggle.isChecked()
        assert second.toggle.isChecked()
        QTest.mouseClick(first.toggle, Qt.MouseButton.LeftButton)
        adapters["commander"].complete()
        QTest.mouseClick(first.toggle, Qt.MouseButton.LeftButton)
        adapters["commander"].complete("停止失败")
        assert first.toggle.isChecked() and first.error.isVisible()
        QTest.mouseClick(first.toggle, Qt.MouseButton.LeftButton)
        adapters["commander"].complete()
        assert not first.toggle.isChecked() and not first.error.isVisible()
    finally:
        window.close()


def test_theme_settings_persistence_no_shortcut_and_no_requests(qt_app, tmp_path):
    adapters, controllers = controls()
    preferences = tmp_path / "preferences.json"
    window = Workbench(controllers, preferences)
    window.show()
    try:
        assert window.theme == "dark"
        window.theme_actions["light"].trigger()
        assert window.theme == "light"
        assert all(action.shortcut().isEmpty() for action in window.theme_actions.values())
        assert all(not adapter.requests for adapter in adapters.values())
        reopened = Workbench(controllers, preferences)
        assert reopened.theme == "light"
        reopened.close()
    finally:
        window.close()


def test_keyboard_wait_and_close_do_not_stop(qt_app):
    adapters, controllers = controls()
    window = Workbench(controllers)
    window.show()
    first = window.rows["commander"]
    first.toggle.setFocus()
    QTest.keyClick(first.toggle, Qt.Key.Key_Space)
    assert controllers["commander"].state.pending
    window.close()
    adapters["commander"].complete()
    assert controllers["commander"].state.running
    assert len(adapters["commander"].requests) == 1


def test_unknown_state_disables_only_affected_row(qt_app):
    adapters, controllers = controls()
    window = Workbench(controllers)
    adapters["commander"].emit(State(Phase.UNKNOWN, True, "状态未确认"))
    assert not window.rows["commander"].toggle.isEnabled()
    assert window.rows["hermes"].toggle.isEnabled()
    assert not controllers["commander"].stop()
    window.close()


def test_small_window_both_themes_fit(qt_app):
    window = Workbench(demo=True)
    window.resize(620, 380)
    window.show()
    try:
        for theme in ("dark", "light"):
            window.set_theme(theme)
            qt_app.processEvents()
            for row in window.rows.values():
                assert row.rect().contains(row.toggle.geometry())
                assert row.rect().contains(row.status.mapTo(row, row.status.rect().bottomRight()))
                assert row.isVisible()
            for group in window.groups.values():
                for label in (group.arrow, group.summary):
                    assert group.header.rect().contains(label.geometry())
                assert group.header.height() >= 48
    finally:
        window.close()


def test_demo_async_success_failure(qt_app):
    adapter = DemoAdapter(delay_ms=40)
    controller = Controller(adapter)
    controller.start()
    assert controller.state.phase == Phase.STARTING
    QTest.qWait(100)
    assert controller.state.phase == Phase.RUNNING
    adapter.fail_next = True
    controller.stop()
    QTest.qWait(100)
    assert controller.state.phase == Phase.FAILED and controller.state.running


def test_single_window_reentry(qt_app):
    import uuid
    key = uuid.uuid4().hex
    owner = WindowInstance(key)
    assert not owner.already_running
    window = Workbench(demo=True)
    owner.attach(window)
    visitor = WindowInstance(key)
    assert visitor.already_running
    qt_app.processEvents()
    window.close()
    owner.server.close()


def test_categories_empty_multiple_expansion_and_keyboard_no_requests(qt_app):
    adapters, controllers = controls()
    window = Workbench(controllers)
    window.show()
    qt_app.processEvents()
    try:
        assert [group.category.title for group in window.groups.values()] == ["ChatGPT", "Claude", "Codex", "Hermes", "OpenCode"]
        assert {key for key, group in window.groups.items() if group.header.isChecked()} == {"chatgpt", "hermes"}
        for key in ("claude", "codex", "opencode"):
            group = window.groups[key]
            window.scroll.ensureWidgetVisible(group.header)
            QTest.mouseClick(group.header, Qt.MouseButton.LeftButton)
            assert group.body.isVisible()
            if key == "opencode":
                assert group.empty.text() == "暂无启动器"
                assert not group.rows
            else:
                assert len(group.rows) == 1
                assert len(group.rows[0].buttons) == 2
        header = window.groups["chatgpt"].header
        window.scroll.ensureWidgetVisible(header)
        header.setFocus()
        QTest.keyClick(header, Qt.Key.Key_Return)
        assert not header.isChecked()
        QTest.keyClick(header, Qt.Key.Key_Space)
        assert header.isChecked()
        QTest.keyClick(header, Qt.Key.Key_Enter)
        assert not header.isChecked()
        assert all(not adapter.requests for adapter in adapters.values())
        assert window.scroll.verticalScrollBar().maximum() > 0
    finally:
        window.close()


def test_hidden_category_observes_pending_failure_and_actual_running(qt_app):
    adapters, controllers = controls()
    window = Workbench(controllers)
    window.show()
    group = window.groups["chatgpt"]
    row = window.rows["commander"]
    try:
        controllers["commander"].start()
        group.header.click()
        assert not row.isVisible()
        assert group.mark.timer.isActive() and "启动中" in group.summary.text()
        adapters["commander"].complete("启动失败")
        assert "有错误" in group.summary.text()
        assert group.header.toolTip() == "启动失败"
        group.header.click()
        assert row.error.isVisible() and not row.toggle.isChecked()
        controllers["commander"].start()
        group.header.click()
        adapters["commander"].complete()
        assert group.summary.text() == "运行中"
        assert not group.mark.timer.isActive()
        controllers["commander"].stop()
        adapters["commander"].complete("停止失败")
        group.header.click()
        assert row.toggle.isChecked() and row.toggle.isEnabled()
        assert row.error.text() == "停止失败"
        adapters["commander"].emit(State(Phase.RUNNING, True, detail="连接断开"))
        assert group.summary.text() == "连接断开" and row.toggle.isChecked()
        assert window.rows["hermes"].toggle.isEnabled()
        assert not adapters["hermes"].requests
    finally:
        window.close()


@pytest.mark.parametrize("values, expected", [
    ({"theme": "light"}, {"chatgpt", "hermes"}),
    ({"expanded_categories": []}, set()),
    ({"expanded_categories": ["claude", "unknown", "claude"]}, {"claude"}),
    ({"expanded_categories": None}, {"chatgpt", "hermes"}),
    ({"expanded_categories": "claude"}, {"chatgpt", "hermes"}),
    ({"expanded_categories": ["claude", 3]}, {"chatgpt", "hermes"}),
    ({"theme": []}, {"chatgpt", "hermes"}),
])
def test_expansion_preferences_defaults_empty_unknown_and_malformed(qt_app, tmp_path, values, expected):
    preferences = tmp_path / "preferences.json"
    preferences.write_text(json.dumps(values), encoding="utf-8")
    window = Workbench(preferences=preferences, demo=True)
    try:
        assert {key for key, group in window.groups.items() if group.header.isChecked()} == expected
    finally:
        window.close()


def test_theme_and_expansion_merge_preserves_unrelated_fields_and_reopen(qt_app, tmp_path):
    preferences = tmp_path / "preferences.json"
    preferences.write_text('{"theme":"dark","future":{"keep":true}}', encoding="utf-8")
    adapters, controllers = controls()
    window = Workbench(controllers, preferences)
    try:
        window.groups["chatgpt"].header.click()
        window.groups["claude"].header.click()
        window.set_theme("light")
        values = json.loads(preferences.read_text(encoding="utf-8"))
        assert values == {"theme": "light", "future": {"keep": True}, "expanded_categories": ["claude", "hermes"]}
        reopened = Workbench(controllers, preferences)
        assert reopened.theme == "light"
        assert {key for key, group in reopened.groups.items() if group.header.isChecked()} == {"claude", "hermes"}
        for group in reopened.groups.values():
            if group.header.isChecked(): group.header.click()
        reopened.set_theme("dark")
        reopened.close()
        final = Workbench(controllers, preferences)
        assert not any(group.header.isChecked() for group in final.groups.values())
        assert final.theme == "dark"
        final.close()
        assert json.loads(preferences.read_text(encoding="utf-8"))["future"] == {"keep": True}
        assert all(not adapter.requests for adapter in adapters.values())
    finally:
        window.close()


def test_corrupt_preferences_recover_without_commands(qt_app, tmp_path):
    preferences = tmp_path / "preferences.json"
    preferences.write_text('{broken', encoding="utf-8")
    window = Workbench(preferences=preferences, demo=True)
    assert window.theme == "dark"
    assert window.groups["chatgpt"].header.isChecked()
    window.set_theme("light")
    assert json.loads(preferences.read_text(encoding="utf-8"))["theme"] == "light"
    window.close()
