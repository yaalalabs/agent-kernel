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
from agentkernel.api.http import RESTAPI
from agentkernel.core.model import AgentReply
from agentkernel.identity.errors import AuthenticationError
from agentkernel.identity.provider.base import IdentityProvider
from agentkernel.identity.provider.request import RequestAuthenticator
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
        return types.SimpleNamespace(session_id=session_id, ending=False)

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


def _wait_for(predicate):
    for _ in range(250):
        if predicate():
            return True
        threading.Event().wait(0.02)
    return False


def test_a_start_while_the_edge_is_ending_starts_a_new_edge_once_it_has_ended():
    """The last caller left, so the edge is closing; the caller rejoins before it has finished."""
    _, client = _client(_Lifecycle())
    _send(client, "start")
    first = _Runner.created[0]
    assert first.started.wait(5)
    first.adapter.ending = True

    _send(client, "start")
    assert len(_Runner.created) == 1  # not while the old edge is still in the room
    first.stop()  # the old edge finishes

    assert _wait_for(lambda: len(_Runner.created) == 2)
    second = _Runner.created[1]
    assert second.started.wait(5) and second.adapter.session_id == "call_1"
    second.stop()


def test_a_repeated_start_during_a_live_call_starts_nothing_after_it_ends():
    handler, client = _client(_Lifecycle())
    _send(client, "start")
    first = _Runner.created[0]
    assert first.started.wait(5)
    _send(client, "start")  # e.g. room_started, then the caller's participant_joined

    first.stop()

    assert _wait_for(lambda: "call_1" not in handler._runners)
    threading.Event().wait(0.1)
    assert len(_Runner.created) == 1


def test_an_end_drops_a_start_held_for_an_ending_edge():
    handler, client = _client(_Lifecycle())
    _send(client, "start")
    first = _Runner.created[0]
    assert first.started.wait(5)
    first.adapter.ending = True
    _send(client, "start")

    _send(client, "end")  # the room finished: nobody to serve

    assert _wait_for(lambda: "call_1" not in handler._runners)
    threading.Event().wait(0.1)
    assert len(_Runner.created) == 1


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


class _RefusingProvider(IdentityProvider):
    name = "refusing"

    async def authenticate(self, credential, context=None):
        raise AuthenticationError(f"not one of ours: {credential}")


def test_the_handler_declares_that_it_authenticates_its_callers():
    assert EdgeLifecycleRESTRequestHandler(_Lifecycle()).authenticates_itself is True


def test_a_platform_signed_webhook_reaches_the_adapter_when_identity_is_configured(monkeypatch):
    # LiveKit signs its webhook in ``Authorization`` without a ``Bearer `` prefix: the identity dependency would refuse it.
    monkeypatch.setattr(RequestAuthenticator, "from_config", classmethod(lambda cls: RequestAuthenticator(_RefusingProvider())))
    client = TestClient(RESTAPI.build_app([EdgeLifecycleRESTRequestHandler(_Lifecycle())]))

    response = client.post("/fake/webhook", json={"action": "start", "session": "call_1"}, headers={"Authorization": "signed-by-platform"})

    assert response.status_code == 200
    assert len(_Runner.created) == 1


def test_process_shutdown_stops_every_live_edge():
    _, client = _client(_Lifecycle())
    _send(client, "start", session="call_1")
    _send(client, "start", session="call_2")
    assert all(runner.started.wait(5) for runner in _Runner.created)

    ThreadRunner.shutdown_event.set()

    assert all(runner.stopped.wait(5) for runner in _Runner.created)


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


def test_a_hanging_stop_is_bounded_and_the_edge_is_cancelled(monkeypatch):
    monkeypatch.setattr(_EdgeRunner, "GRACEFUL_STOP_TIMEOUT_SECONDS", 0.05)
    adapter = FakeStatefulEdgeAdapter()
    running = threading.Event()

    async def run_until_stopped():
        running.set()
        await asyncio.Event().wait()

    async def hanging_stop():
        await asyncio.Event().wait()

    adapter.start = run_until_stopped
    adapter.stop = hanging_stop
    runner = _EdgeRunner(adapter)
    thread = threading.Thread(target=runner.start, daemon=True)
    thread.start()
    assert running.wait(5)

    runner.stop()
    thread.join(5)

    assert not thread.is_alive()
    assert StatefulEdgeRegistry.get(adapter.session_id) is None


def test_a_failed_start_is_not_retried_and_frees_the_session():
    adapter = FakeStatefulEdgeAdapter()
    attempts = []

    async def failing_start():
        attempts.append(True)
        raise RuntimeError("bad credentials")

    adapter.start = failing_start

    with pytest.raises(RuntimeError, match="bad credentials"):
        _EdgeRunner(adapter).start()

    assert len(attempts) == 1
    assert StatefulEdgeRegistry.get(adapter.session_id) is None


def test_an_edge_that_ends_by_itself_is_noticed_at_once():
    adapter = FakeStatefulEdgeAdapter()
    running = threading.Event()

    async def ends_soon():
        running.set()
        await asyncio.sleep(0.05)

    adapter.start = ends_soon
    thread = threading.Thread(target=_EdgeRunner(adapter).start, daemon=True)
    thread.start()

    assert running.wait(5)
    thread.join(5)  # nothing polls: the runner was woken by the edge ending
    assert not thread.is_alive()
    assert StatefulEdgeRegistry.get(adapter.session_id) is None


def test_a_stop_request_is_noticed_at_once():
    adapter = FakeStatefulEdgeAdapter()
    running = threading.Event()
    gate = {}

    async def run_until_stopped():
        gate["event"] = asyncio.Event()
        running.set()
        await gate["event"].wait()

    async def stop():
        gate["event"].set()

    adapter.start = run_until_stopped
    adapter.stop = stop
    runner = _EdgeRunner(adapter)
    thread = threading.Thread(target=runner.start, daemon=True)
    thread.start()
    assert running.wait(5)

    runner.stop()
    thread.join(5)  # nothing polls: stop() woke the runner

    assert not thread.is_alive()


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
