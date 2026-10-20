"""One generation seam: callers never speak an agent's native protocol."""
from __future__ import annotations

from copy import deepcopy
from typing import Protocol

from .files import ChatterError


AGENTS = {"codex": "Codex", "deepseek": "DeepSeek Harness"}


class Adapter(Protocol):
    def account(self) -> dict: ...
    def authenticate(self, action: str, **values) -> dict: ...
    def generate(self, request: dict, cancelled, emit) -> dict: ...
    def close(self) -> None: ...


def selection(models, value):
    """Resolve a selection before admitting a task, never silently substitute."""
    model_id, effort = value.get("model"), value.get("effort")
    model = next((m for m in models if m["id"] == model_id), None) if model_id else next((m for m in models if m.get("default")), None)
    if model is None:
        raise ChatterError("所选模型不可用，请打开 Models 重新选择")
    if effort and effort not in [e["id"] for e in model.get("efforts", [])]:
        raise ChatterError("该模型不支持已保存的推理强度，请打开 Models 重新选择")
    return {"model": model["id"], "effort": effort}


class Providers:
    def __init__(self, service, factories=None):
        self.service = service
        self.adapters = {}
        if factories is None:
            from .codex import Codex, DemoCodex
            from .deepseek import DeepSeek
            if service.root:
                factories = {
                    "codex": lambda: Codex(service.root / "staging/provider", service.store.setting("codex_cli")),
                    "deepseek": lambda: DeepSeek(service.root / "providers/deepseek", service.store.setting("deepseek_cli"), service.store.setting("deepseek_auth", "account")),
                }
            else:
                factories = {key: lambda key=key: DemoCodex(key) for key in AGENTS}
        self.factories = factories

    def adapter(self, agent=None):
        agent = agent or self.service.store.setting("agent", "codex")
        if agent not in self.factories:
            raise ChatterError("未知 Agent")
        if agent not in self.adapters:
            self.adapters[agent] = self.factories[agent]()
        return self.adapters[agent]

    def account(self, agent=None):
        agent = agent or self.service.store.setting("agent", "codex")
        return self.adapter(agent).account() | {"agent": agent, "name": AGENTS[agent]}

    def authenticate(self, agent, action, **values):
        return self.adapter(agent).authenticate(action, **values)

    def bind(self, session_id, task_id=None, override=None):
        agent = self.service.store.setting("agent", "codex")
        account = self.account(agent)
        if not account["connected"]:
            raise ChatterError("请先在设置中连接当前 Agent")
        task = self.service.store.get("tasks", task_id) if task_id else None
        if task and task.get("execution"):
            execution = deepcopy(task["execution"])
            if execution["agent"] != agent:
                raise ChatterError("请先完成或取消原 Agent 的工程任务")
            selection(account["models"], execution)
            return execution
        session = self.service.store.get("sessions", session_id)
        value = override if override is not None else session.get("model_preferences", {}).get(agent, {})
        return selection(account["models"], value) | {"agent": agent}

    def generate(self, request, cancelled, emit):
        return self.adapter(request["execution"]["agent"]).generate(request, cancelled, emit)

    def invalidate(self, agent):
        adapter = self.adapters.pop(agent, None)
        if adapter:
            adapter.close()

    def close(self):
        for agent in list(self.adapters):
            self.invalidate(agent)
