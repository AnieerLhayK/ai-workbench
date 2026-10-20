"""Exercise the built React interface through the real private Qt channel."""
from pathlib import Path
import os
import time

import pytest
from PySide6.QtTest import QTest


def test_native_webchannel_diagnosis_and_confirmation(request, tmp_path):
    if os.environ.get("E_CHATTER_RUN_NATIVE") != "1":
        pytest.skip("native QtWebEngine requires a separate desktop process; see e-Chatter verification instructions")
    qt_app = request.getfixturevalue("qt_app")
    from ai_workbench.e_chatter.app import Window
    from ai_workbench.e_chatter.service import Service
    if not (Path(__file__).parents[1] / "src/ai_workbench/e_chatter/web/index.html").is_file():
        pytest.skip("build frontend to run native WebChannel integration")
    service = Service()
    service.seed_demo()
    window = Window(service)
    loaded = []
    loading_errors = []
    window.page.loadingChanged.connect(lambda info: loading_errors.append((str(info.status()), info.errorCode(), info.errorString())))
    window.page.renderProcessTerminated.connect(lambda status, code: loading_errors.append((str(status), code)))
    window.view.loadFinished.connect(loaded.append)
    window.show()

    def javascript(source):
        values = []
        window.page.runJavaScript(source, values.append)
        deadline = time.monotonic() + 15
        while not values and time.monotonic() < deadline:
            QTest.qWait(20)
        assert values
        return values[0]

    def wait_for(predicate):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(40)
        raise AssertionError("native WebChannel did not finish")

    try:
        wait_for(lambda: bool(loaded))
        assert loaded[-1], ("built local frontend failed to load", loading_errors)
        wait_for(lambda: javascript("!!Array.from(document.querySelectorAll('button')).find(x=>x.textContent==='doctor')"))
        javascript("Array.from(document.querySelectorAll('button')).find(x=>x.textContent==='doctor').click()")
        wait_for(lambda: len(service.snapshot()["records"]) == 2)
        assert {r["kind"] for r in service.snapshot()["records"]} == {"diagnosis", "handoff"}
        javascript("Array.from(document.querySelectorAll('button')).find(x=>x.textContent==='Generator').click()")
        wait_for(lambda: javascript("!!document.querySelector('dialog[open]')"))
        assert not any(t["kind"] == "generator" for t in service.snapshot()["tasks"])
        javascript("Array.from(document.querySelector('dialog').querySelectorAll('button')).find(x=>x.textContent==='取消').click()")
        wait_for(lambda: javascript("!document.querySelector('dialog[open]')"))
        javascript("Array.from(document.querySelectorAll('button')).find(x=>x.textContent==='Models').click()")
        wait_for(lambda: javascript("!!document.querySelector('.models-popover')"))
        javascript("Array.from(document.querySelectorAll('.models-popover label')).find(x=>x.textContent==='演示模型').querySelector('input').click()")
        wait_for(lambda: service.store.rows("sessions")[0].get("model_preferences", {}).get("codex", {}).get("model") == "demo")
        javascript("document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true}))")
        wait_for(lambda: javascript("!document.querySelector('.models-popover')"))
    finally:
        window.close()
        QTest.qWait(100)
        service.store.close()
