"""EdgeLifecycleRESTRequestHandler: one stateful edge per live connection, started and ended by a platform's lifecycle webhooks.

The handler's tests stand in a fake for ``_EdgeRunner``; the runner's own tests, with its outbound registration, follow them.
"""

import asyncio
import threading
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import agentkernel.integration.adapter.lifecycle as lifecycle_module
from agentkernel.core.model import AgentReply
from agentkernel.integration.adapter import EdgeLifecycleAdapter, EdgeLifecycleEvent, EdgeLifecycleRESTRequestHandler
from agentkernel.integration.adapter.base import Source, StatefulEdgeAdapter
from agentkernel.integration.adapter.lifecycle import _EdgeRunner
from agentkernel.integration.adapter.registry import StatefulEdgeRegistry
from agentkernel.pipeline.thread_runner import ThreadRunner


class _Runner:
    """Stands in for _EdgeRunner: start() blocks until stop(), as the real one does."""

    created: list["_Runner"] = []

    def __init__(self, adapter):
        self.adapter = adapter
        self.started = threading.Event()
        self.stopped = threading.Event()
        _Runner.created.append(self)

    def start(self):
        self.started.set()
        self.stopped.wait(5)

    def stop(self):
        self.stopped.set()


class _Lifecycle(EdgeLifecycleAdapter):
    """Reads the event from the JSON body: {"action": "start" | "end" | null, "session": "..."}."""

    name = "fake"
    webhook_path = "/fake/webhook"

    def __init__(self, reject=False, starts=lambda session_id: True):
        self.reject = reject
        self.starts = starts

    async def parse(self, raw):
        if self.reject:
            raise HTTPException(status_code=401, detail="bad signature")
        body = await raw.json()
        return EdgeLifecycleEvent(body["session"], start=body["action"] == "start") if body["action"] else None

    def create_edge(self, session_id):
        return types.SimpleNamespace(session_id=session_id)

    def should_start(self, session_id):
        return self.starts(session_id)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # The handler tests see the fake runner; the runner tests below use the real class imported above.
    _Runner.created = []
    monkeypatch.setattr(lifecycle_module, "_EdgeRunner", _Runner)
    StatefulEdgeRegistry.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    StatefulEdgeRegistry.reset()
    ThreadRunner.shutdown_event.clear()


def _client(adapter):
    handler = EdgeLifecycleRESTRequestHandler(adapter)
    app = FastAPI()
    app.include_router(handler.get_router())
    return handler, TestClient(app)


def _send(client, action, session="call_1"):
    return client.post("/fake/webhook", json={"action": action, "session": session})


def test_start_runs_one_edge_for_the_session():
    _, client = _client(_Lifecycle())

    assert _send(client, "start").json() == {"status": "ok"}

    (runner,) = _Runner.created
    assert runner.started.wait(5)
    assert runner.adapter.session_id == "call_1"
    runner.stop()


def test_a_repeated_start_is_ignored():
    _, client = _client(_Lifecycle())
    _send(client, "start")
    _send(client, "start")

    assert len(_Runner.created) == 1
    _Runner.created[0].stop()


def test_end_stops_the_edge_and_frees_the_session():
    handler, client = _client(_Lifecycle())
    _send(client, "start")
    runner = _Runner.created[0]
    assert runner.started.wait(5)

    _send(client, "end")

    assert runner.stopped.is_set()
    for _ in range(100):
        if "call_1" not in handler._runners:
            break
        threading.Event().wait(0.02)
    assert "call_1" not in handler._runners


def test_a_session_can_start_again_after_it_ended():
    handler, client = _client(_Lifecycle())
    _send(client, "start")
    _send(client, "end")
    for _ in range(100):
        if "call_1" not in handler._runners:
            break
        threading.Event().wait(0.02)

    _send(client, "start")

    assert len(_Runner.created) == 2
    _Runner.created[1].stop()


def test_should_start_chooses_the_sessions():
    _, client = _client(_Lifecycle(starts=lambda session_id: session_id.startswith("call_")))

    _send(client, "start", session="meeting_1")

    assert _Runner.created == []


def test_a_delivery_that_is_no_event_starts_nothing():
    _, client = _client(_Lifecycle())

    assert _send(client, None).status_code == 200
    assert _Runner.created == []


def test_a_rejected_delivery_starts_nothing():
    _, client = _client(_Lifecycle(reject=True))

    assert _send(client, "start").status_code == 401
    assert _Runner.created == []


def test_needs_a_webhook_path():
    class NoRoute(_Lifecycle):
        webhook_path = ""

    with pytest.raises(ValueError, match="webhook_path"):
        EdgeLifecycleRESTRequestHandler(NoRoute())


def test_no_edge_starts_once_the_process_is_shutting_down():
    _, client = _client(_Lifecycle())
    ThreadRunner.shutdown_event.set()

    _send(client, "start")

    assert _Runner.created == []


# -- _EdgeRunner: the per-edge half, with its outbound registration ----------------------------------------------------


class FakeStatefulEdgeAdapter(StatefulEdgeAdapter):
    name = "fakegateway"

    def __init__(self):
        self.started = False
        self.session_id = "test-session-123"

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        pass

    async def deliver(self, reply: AgentReply, reply_context: dict[str, str]) -> None:
        pass

    async def deliver_chunk(self, chunk, reply_context: dict[str, str]) -> None:
        pass

    async def deliver_error(self, message: str, reply_context: dict[str, str]) -> None:
        pass


def test_rejects_a_non_realtime_source():
    class WebhookGateway(FakeStatefulEdgeAdapter):
        source = Source.WEBHOOK

    with pytest.raises(ValueError, match="not EdgeLifecycleRESTRequestHandler"):
        _EdgeRunner(WebhookGateway())


def test_adapter_property_is_the_hosted_adapter():
    adapter = FakeStatefulEdgeAdapter()
    assert _EdgeRunner(adapter).adapter is adapter


def test_start_registers_and_unregisters_the_outbound_adapter():
    adapter = FakeStatefulEdgeAdapter()
    was_registered = False

    async def fake_start():
        adapter.started = True
        nonlocal was_registered
        # Check if it's registered WHILE running
        was_registered = StatefulEdgeRegistry.get(adapter.session_id) is adapter

    adapter.start = fake_start
    _EdgeRunner(adapter).start()

    assert adapter.started is True
    assert was_registered is True
    # Verify it cleans up properly after the blocking loop exits
    assert StatefulEdgeRegistry.get(adapter.session_id) is None


def test_stop_ends_this_edge_only_and_unregisters_it():
    adapter = FakeStatefulEdgeAdapter()
    running = threading.Event()
    stopped = []

    async def run_until_stopped():
        running.set()
        await asyncio.Event().wait()

    async def fake_stop():
        stopped.append(True)

    adapter.start = run_until_stopped
    adapter.stop = fake_stop
    runner = _EdgeRunner(adapter)
    thread = threading.Thread(target=runner.start, daemon=True)
    thread.start()
    assert running.wait(5)

    runner.stop()
    thread.join(_EdgeRunner.GRACEFUL_STOP_TIMEOUT_SECONDS + 5)

    assert not thread.is_alive()
    assert stopped == [True]
    assert StatefulEdgeRegistry.get(adapter.session_id) is None


def test_an_edge_stopped_before_it_starts_never_starts_its_adapter():
    adapter = FakeStatefulEdgeAdapter()
    started = []

    async def fake_start():
        started.append(True)

    adapter.start = fake_start
    runner = _EdgeRunner(adapter)

    runner.stop()
    runner.start()

    assert started == []
    assert StatefulEdgeRegistry.get(adapter.session_id) is None


class TestRegistryUnregister:
    def test_unregister_with_an_adapter_removes_only_that_adapter(self):
        old, newer = FakeStatefulEdgeAdapter(), FakeStatefulEdgeAdapter()
        StatefulEdgeRegistry.register(old, session_id="s")
        StatefulEdgeRegistry.register(newer, session_id="s")

        StatefulEdgeRegistry.unregister("s", old)

        assert StatefulEdgeRegistry.get("s") is newer

        StatefulEdgeRegistry.unregister("s", newer)
        assert StatefulEdgeRegistry.get("s") is None
