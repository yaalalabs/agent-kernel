"""GatewayRunner: hosting a stateful gateway adapter, and its outbound registration."""

from typing import Dict

import pytest

from agentkernel.core.model import AgentReply
from agentkernel.integration.adapter.base import Source, StatefulEdgeAdapter
from agentkernel.integration.adapter.gateway import GatewayRunner
from agentkernel.integration.adapter.registry import StatefulEdgeRegistry


class FakeStatefulEdgeAdapter(StatefulEdgeAdapter):
    name = "fakegateway"

    def __init__(self):
        self.started = False
        self.session_id = "test-session-123"

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        pass

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        pass

    async def deliver_chunk(self, chunk, reply_context: Dict[str, str]) -> None:
        pass

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_registry():
    StatefulEdgeRegistry.reset()
    yield
    StatefulEdgeRegistry.reset()


def test_rejects_a_non_realtime_source():
    class WebhookGateway(FakeStatefulEdgeAdapter):
        source = Source.WEBHOOK

    with pytest.raises(ValueError, match="not GatewayRunner"):
        GatewayRunner(WebhookGateway())


def test_adapter_property_is_the_hosted_adapter():
    adapter = FakeStatefulEdgeAdapter()
    assert GatewayRunner(adapter).adapter is adapter


def test_start_registers_and_unregisters_the_outbound_adapter():
    adapter = FakeStatefulEdgeAdapter()
    was_registered = False

    async def fake_start():
        adapter.started = True
        nonlocal was_registered
        # Check if it's registered WHILE running
        was_registered = StatefulEdgeRegistry.get(adapter.session_id) is adapter

    adapter.start = fake_start
    GatewayRunner(adapter).start()

    assert adapter.started is True
    assert was_registered is True
    # Verify it cleans up properly after the blocking loop exits
    assert StatefulEdgeRegistry.get(adapter.session_id) is None


class StayingGateway(FakeStatefulEdgeAdapter):
    """A gateway that stays in its room until stopped, as a live one does."""

    def __init__(self, session_id="room-1", fail=False):
        super().__init__()
        self.session_id = session_id
        self.fail = fail
        self.stopped = False
        self._left = None

    async def start(self) -> None:
        import asyncio

        if self.fail:
            raise RuntimeError("could not join the room")
        self._left = asyncio.Event()
        self.started = True
        await self._left.wait()

    async def stop(self) -> None:
        self.stopped = True
        if self._left is not None:
            self._left.set()


def _wait(condition, timeout=3.0):
    import time

    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


class TestGatewayRunnerStop:
    def test_stop_from_another_thread_ends_a_running_gateway(self):
        import threading

        adapter = StayingGateway()
        runner = GatewayRunner(adapter)
        host = threading.Thread(target=runner.start, daemon=True)
        host.start()
        _wait(lambda: adapter.started)
        assert StatefulEdgeRegistry.get("room-1") is adapter

        assert runner.stop(timeout=5) is True

        host.join(timeout=1)
        assert adapter.stopped and not host.is_alive()
        assert StatefulEdgeRegistry.get("room-1") is None

    def test_a_gateway_stopped_before_it_starts_never_joins(self):
        adapter = StayingGateway()
        runner = GatewayRunner(adapter)

        assert runner.stop(timeout=1) is True  # nothing was running
        runner.start()  # returns at once

        assert adapter.started is False
        assert StatefulEdgeRegistry.get("room-1") is None

    def test_a_gateway_leaving_slowly_does_not_unregister_its_replacement(self):
        import asyncio
        import threading

        release = threading.Event()

        class SlowToLeave(StayingGateway):
            async def stop(self):
                while not release.is_set():
                    await asyncio.sleep(0.01)
                await super().stop()

        old, new = SlowToLeave("room-1"), StayingGateway("room-1")
        old_runner, new_runner = GatewayRunner(old), GatewayRunner(new)
        threading.Thread(target=old_runner.start, daemon=True).start()
        _wait(lambda: old.started)
        assert old_runner.stop(timeout=0) is False  # still leaving
        threading.Thread(target=new_runner.start, daemon=True).start()
        _wait(lambda: new.started and StatefulEdgeRegistry.get("room-1") is new)

        release.set()
        assert old_runner.stop(timeout=5)

        assert StatefulEdgeRegistry.get("room-1") is new
        assert new_runner.stop(timeout=5)
        assert StatefulEdgeRegistry.get("room-1") is None

    def test_a_gateway_that_fails_to_start_leaves_nothing_registered(self):
        runner = GatewayRunner(StayingGateway(fail=True))

        with pytest.raises(RuntimeError, match="could not join the room"):
            runner.start()

        assert StatefulEdgeRegistry.get("room-1") is None
        assert runner.stop(timeout=1) is True  # start() has returned
