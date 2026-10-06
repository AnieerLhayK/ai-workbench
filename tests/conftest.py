import pytest
from ai_workbench.app import create_application

from ai_workbench.lifecycle import Completion, State


class ControlledAdapter:
    def __init__(self):
        self.requests: list[tuple[bool, Completion]] = []

    def request(self, running: bool, complete: Completion) -> None:
        self.requests.append((running, complete))

    def observe(self, callback):
        self.observer = callback
        callback(State())
        return lambda: setattr(self, "observer", None)

    def emit(self, state):
        self.observer(state)

    def complete(self, error: str | None = None) -> None:
        self.requests[-1][1](error)


@pytest.fixture(scope="session")
def qt_app():
    return create_application()


@pytest.fixture
def adapter():
    return ControlledAdapter()
