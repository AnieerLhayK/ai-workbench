import threading

import pytest

from ai_workbench.e_diary.providers import Providers, DeepSeekAdapter
from ai_workbench.e_diary.library import DiaryError


def test_provider_is_selected_per_request_without_fallback(tmp_path):
    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        def generate(self, prompt, directory, cancelled, progress):
            calls.append((self.name, prompt))
            if self.name == "deepseek":
                raise DiaryError("offline")
            return {"title": "title", "body": "body", "files": []}

    config = {"provider": "codex"}
    providers = Providers(config, {name: Provider(name) for name in ("codex", "deepseek")})
    selected = providers.snapshot()
    assert providers.generate("private evidence", tmp_path, threading.Event(), lambda _: None)["body"] == "body"
    config["provider"] = "deepseek"
    assert selected.generate("second evidence", tmp_path, threading.Event(), lambda _: None)["body"] == "body"
    with pytest.raises(DiaryError, match="offline"):
        providers.generate("private evidence", tmp_path, threading.Event(), lambda _: None)
    assert calls == [("codex", "private evidence"), ("codex", "second evidence"), ("deepseek", "private evidence")]


def test_deepseek_uses_diary_schema_and_propagates_cancellation(tmp_path):
    class Harness:
        def account(self, cancelled=None):
            cancelled.set()
            return {"connected": True, "models": [{"id": "model-one"}]}

        def generate(self, request, cancelled, emit):
            assert request["payload"]["user"] == "private evidence"
            assert request["execution"]["model"] == "model-one"
            assert cancelled.is_set()
            raise DiaryError("cancelled")

        def close(self):
            pass

    cancelled = threading.Event()
    adapter = DeepSeekAdapter({"data_root": str(tmp_path)}, harness_factory=lambda **_: Harness())
    with pytest.raises(DiaryError, match="cancelled"):
        adapter.generate("private evidence", tmp_path, cancelled, lambda _: None)


def test_settings_persist_explicit_provider(qt_app, tmp_path):
    from ai_workbench.e_diary.pages import Preferences
    from ai_workbench.e_diary.settings import Settings
    config = {"codex_cli": str(tmp_path / "codex.exe"), "staging_root": str(tmp_path)}
    settings = Settings(tmp_path, config)
    page = Preferences(settings, config, lambda _: None)
    page.provider.setCurrentIndex(page.provider.findData("deepseek"))
    page.save()
    assert settings.data["runtime"]["provider"] == "deepseek"
    assert config["provider"] == "deepseek"


def test_deepseek_authentication_uses_configured_harness(tmp_path):
    calls = []

    class Harness:
        def authenticate(self, action, **values):
            calls.append((action, values))
            return {"pending": False}

        def close(self):
            calls.append(("close", {}))

    adapter = DeepSeekAdapter({"data_root": str(tmp_path), "deepseek_auth": "api_key"},
                              harness_factory=lambda **_: Harness())
    adapter.authenticate("save_key", key="synthetic")
    assert calls == [("save_key", {"key": "synthetic"}), ("close", {})]


def test_login_without_pending_attempt_is_not_success_unless_connected(tmp_path):
    class Harness:
        def authenticate(self, action, **values):
            return {"pending": False}

        def account(self):
            return {"connected": False}

        def close(self):
            pass

    adapter = DeepSeekAdapter({"data_root": str(tmp_path)}, harness_factory=lambda **_: Harness())
    with pytest.raises(DiaryError, match="登录未完成"):
        adapter.authenticate("login")
