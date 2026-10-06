import pytest

from ai_workbench.lifecycle import Controller, Phase
from conftest import ControlledAdapter


def test_delayed_start_stop_and_duplicate_requests(adapter):
    controller = Controller(adapter)
    seen = []
    unsubscribe = controller.observe(seen.append)
    assert controller.start()
    assert controller.state.phase == Phase.STARTING
    assert not controller.state.running
    assert not controller.start()
    assert not controller.stop()
    assert len(adapter.requests) == 1
    adapter.complete()
    assert controller.state.phase == Phase.RUNNING
    assert not controller.start()
    assert controller.stop()
    assert controller.state.phase == Phase.STOPPING
    assert controller.state.running
    assert not controller.start()
    assert not controller.stop()
    adapter.complete()
    assert controller.state.phase == Phase.STOPPED
    assert not controller.stop()
    assert [state.phase for state in seen] == [
        Phase.STOPPED, Phase.STARTING, Phase.RUNNING, Phase.STOPPING, Phase.STOPPED,
    ]
    unsubscribe()
    controller.start()
    assert len(seen) == 5


@pytest.mark.parametrize("initial_running", [False, True])
def test_failure_preserves_actual_state_and_allows_retry(adapter, initial_running):
    controller = Controller(adapter)
    if initial_running:
        controller.start()
        adapter.complete()
    request = controller.stop if initial_running else controller.start
    request()
    adapter.complete("expected failure")
    assert controller.state.phase == Phase.FAILED
    assert controller.state.running == initial_running
    assert controller.state.error == "expected failure"
    assert request()
    assert controller.state.error is None
    adapter.complete()
    assert controller.state.running != initial_running


def test_late_duplicate_completion_does_not_finish_new_request(adapter):
    controller = Controller(adapter)
    controller.start()
    old_completion = adapter.requests[0][1]
    adapter.complete()
    controller.stop()
    old_completion("late failure")
    assert controller.state.phase == Phase.STOPPING
    adapter.complete()
    old_completion()
    assert controller.state.phase == Phase.STOPPED


def test_tools_are_independent(adapter):
    other_adapter = ControlledAdapter()
    commander, hermes = Controller(adapter), Controller(other_adapter)
    commander.start()
    assert hermes.state.phase == Phase.STOPPED
    hermes.start()
    other_adapter.complete("Hermes failure")
    assert commander.state.phase == Phase.STARTING
    adapter.complete()
    assert commander.state.running
    assert hermes.state.phase == Phase.FAILED


def test_adapter_exception_is_observable_failure():
    class BrokenAdapter:
        def observe(self, callback):
            return lambda: None

        def request(self, running, complete):
            raise RuntimeError("adapter failed")

    controller = Controller(BrokenAdapter())
    assert controller.start()
    assert controller.state.phase == Phase.FAILED
    assert controller.state.error == "adapter failed"
