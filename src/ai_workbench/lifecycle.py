"""Lifecycle state machine. Adapters complete requests on the caller's thread."""
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Phase(str, Enum):
    CHECKING = "checking"
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class State:
    phase: Phase = Phase.STOPPED
    running: bool = False
    error: str | None = None
    detail: str = ""

    @property
    def pending(self) -> bool:
        return self.phase in (Phase.STARTING, Phase.STOPPING)

    @property
    def available(self) -> bool:
        return not self.pending and self.phase not in (Phase.CHECKING, Phase.UNKNOWN)


Completion = Callable[[str | None], None]


class Adapter(Protocol):
    def request(self, running: bool, complete: Completion) -> None:
        """Complete once with None on success or an error message on failure."""

    def observe(self, callback: Callable[[State], None]) -> Callable[[], None]:
        """Publish observed state on the caller's thread and return unsubscribe."""


class Controller:
    """Own one tool's lifecycle; ignore duplicate and stale completions."""

    def __init__(self, adapter: Adapter):
        self._adapter = adapter
        self._state = State()
        self._observers: list[Callable[[State], None]] = []
        self._generation = 0
        self._unsubscribe = adapter.observe(self._publish)

    @property
    def state(self) -> State:
        return self._state

    def observe(self, callback: Callable[[State], None]) -> Callable[[], None]:
        self._observers.append(callback)
        callback(self._state)
        return lambda: self._observers.remove(callback)

    def start(self) -> bool:
        return self._request(True)

    def stop(self) -> bool:
        return self._request(False)

    def _publish(self, state: State) -> None:
        self._state = state
        for observer in tuple(self._observers):
            observer(state)

    def _request(self, running: bool) -> bool:
        if not self._state.available or running == self._state.running:
            return False
        self._generation += 1
        generation = self._generation
        previous = self._state.running
        self._publish(State(Phase.STARTING if running else Phase.STOPPING, previous))

        def complete(error: str | None = None) -> None:
            if generation != self._generation or not self._state.pending:
                return
            if error is not None:
                self._publish(State(Phase.FAILED, previous, error or "Operation failed"))
            else:
                self._publish(State(Phase.RUNNING if running else Phase.STOPPED, running))

        try:
            self._adapter.request(running, complete)
        except Exception as error:
            complete(str(error) or type(error).__name__)
        return True
