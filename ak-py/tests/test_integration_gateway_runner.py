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


class BackgroundEdge(FakeStatefulEdgeAdapter):
    """An edge that is ready as soon as it starts, then runs until stopped, as a real room gateway does."""

    def __init__(self, session_id="bg-1", ready=True, fail=None):
        super().__init__()
        self.session_id = session_id
        self._becomes_ready = ready
        self._fail = fail
        self.stopped = None

    async def start(self) -> None:
        import asyncio

        if self._fail is not None:
            raise self._fail
        self._stop = asyncio.Event()
        self.started = True
        if self._becomes_ready:
            self._mark_ready()
        await self._stop.wait()

    async def stop(self) -> None:
        self.stopped = True
        self._stop.set()


class TestStartBackground:
    def test_it_returns_once_the_edge_is_ready_and_runs_until_stopped(self):
        edge = BackgroundEdge()
        runner = GatewayRunner(edge)

        runner.start_background(ready_timeout=5)

        assert runner.running
        assert StatefulEdgeRegistry.get("bg-1") is edge
        runner.stop()
        assert not runner.running
        assert edge.stopped is True

    def test_a_start_failure_is_re_raised_to_the_caller(self):
        runner = GatewayRunner(BackgroundEdge(fail=RuntimeError("no room")))

        with pytest.raises(RuntimeError, match="no room"):
            runner.start_background(ready_timeout=5)

        assert StatefulEdgeRegistry.get("bg-1") is None

    def test_an_edge_that_is_never_ready_times_out_and_is_stopped(self):
        edge = BackgroundEdge(ready=False)
        runner = GatewayRunner(edge)

        with pytest.raises(TimeoutError):
            runner.start_background(ready_timeout=0.2)

        assert not runner.running
        assert edge.stopped is True
        assert StatefulEdgeRegistry.get("bg-1") is None

    def test_starting_twice_is_refused(self):
        runner = GatewayRunner(BackgroundEdge())
        runner.start_background(ready_timeout=5)
        try:
            with pytest.raises(RuntimeError, match="already started"):
                runner.start_background(ready_timeout=5)
        finally:
            runner.stop()

    def test_stop_is_idempotent_and_safe_before_a_start(self):
        runner = GatewayRunner(BackgroundEdge())
        runner.stop()
        runner.start_background(ready_timeout=5)

        runner.stop()
        runner.stop()

        assert not runner.running
        assert StatefulEdgeRegistry.get("bg-1") is None

    def test_two_background_gateways_stay_independent(self):
        first, second = BackgroundEdge("bg-1"), BackgroundEdge("bg-2")
        first_runner, second_runner = GatewayRunner(first), GatewayRunner(second)
        first_runner.start_background(ready_timeout=5)
        second_runner.start_background(ready_timeout=5)
        try:
            first_runner.stop()

            assert not first_runner.running
            assert second_runner.running
            assert StatefulEdgeRegistry.get("bg-1") is None
            assert StatefulEdgeRegistry.get("bg-2") is second
        finally:
            second_runner.stop()

    def test_a_failure_in_one_background_gateway_does_not_touch_the_other(self):
        good = GatewayRunner(BackgroundEdge("bg-2"))
        good.start_background(ready_timeout=5)
        try:
            with pytest.raises(RuntimeError):
                GatewayRunner(BackgroundEdge("bg-1", fail=RuntimeError("boom"))).start_background(ready_timeout=5)

            assert good.running
        finally:
            good.stop()

    def test_the_process_shutdown_event_stops_a_background_gateway(self):
        from agentkernel.pipeline.thread_runner import ThreadRunner

        edge = BackgroundEdge()
        runner = GatewayRunner(edge)
        runner.start_background(ready_timeout=5)
        ThreadRunner.shutdown_event.set()
        try:
            runner._thread.join(timeout=5)
            assert not runner.running
            assert edge.stopped is True
        finally:
            ThreadRunner.shutdown_event.clear()


class TestRegistryEnded:
    def test_unregister_with_an_adapter_removes_only_that_adapter(self):
        old, newer = FakeStatefulEdgeAdapter(), FakeStatefulEdgeAdapter()
        StatefulEdgeRegistry.register(old, session_id="s")
        StatefulEdgeRegistry.register(newer, session_id="s")

        StatefulEdgeRegistry.unregister("s", old)

        assert StatefulEdgeRegistry.get("s") is newer
        assert not StatefulEdgeRegistry.recently_ended("s")

        StatefulEdgeRegistry.unregister("s", newer)
        assert StatefulEdgeRegistry.get("s") is None
        assert StatefulEdgeRegistry.recently_ended("s")

    def test_recently_ended_expires(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr("agentkernel.integration.adapter.registry.time.time", lambda: now[0])
        StatefulEdgeRegistry.register(FakeStatefulEdgeAdapter(), session_id="s")
        StatefulEdgeRegistry.unregister("s")

        assert StatefulEdgeRegistry.recently_ended("s")
        now[0] += StatefulEdgeRegistry.ENDED_TTL_SECONDS - 1
        assert StatefulEdgeRegistry.recently_ended("s")
        now[0] += 2
        assert not StatefulEdgeRegistry.recently_ended("s")
        assert "s" not in StatefulEdgeRegistry._ended

    def test_register_clears_the_mark_and_reset_clears_all(self):
        StatefulEdgeRegistry.unregister("s")
        StatefulEdgeRegistry.unregister("t")
        StatefulEdgeRegistry.register(FakeStatefulEdgeAdapter(), session_id="s")

        assert not StatefulEdgeRegistry.recently_ended("s")
        assert StatefulEdgeRegistry.recently_ended("t")
        StatefulEdgeRegistry.reset()
        assert not StatefulEdgeRegistry.recently_ended("t")


class TestHooks:
    def test_hooks_run_in_order_off_the_calling_thread_and_a_raising_hook_does_not_stop_the_next(self):
        import threading

        edge = FakeStatefulEdgeAdapter()
        seen, threads = [], []

        def hook(value):
            threads.append(threading.current_thread().name)
            if value == 2:
                raise ValueError("bad hook")
            seen.append(value)

        for value in (1, 2, 3):
            edge._dispatch_hook(hook, value)
        edge._close_hooks()

        assert seen == [1, 3]
        assert all(name.startswith("edge-hooks-test-session-123") for name in threads)

    def test_a_call_after_close_is_dropped_and_close_is_repeatable(self):
        edge = FakeStatefulEdgeAdapter()
        seen = []
        edge._dispatch_hook(seen.append, 1)
        edge._close_hooks()
        edge._close_hooks()

        edge._dispatch_hook(seen.append, 2)

        assert seen == [1]

    def test_an_edge_that_never_dispatches_starts_no_thread(self):
        edge = FakeStatefulEdgeAdapter()
        edge._close_hooks()
        assert edge._hooks is None
