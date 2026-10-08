"""AG-UI over the queue pipeline (spec #710).

The four cases that carry the design are the ones that fail against the version of it that went
to review: a response store's chunk-streaming capability says nothing about whether another
process can read it; the marker has to survive the runner hop or the Response Handler never sees
it; the client's forwardedProps and context cannot cross on the session; and the state baseline
has to be taken after the inbound state is applied, not before.
"""

import json
import threading
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from agentkernel.auth.authoriser import Authoriser
from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import ExecutionMode, StreamChunk
from agentkernel.core.util.factory import AKConfigError
from agentkernel.integration.agui.pipeline import AGUIPipelineRequestHandler
from agentkernel.integration.agui.run_input import AGUIRunEnvelope, AGUIRunRequest
from agentkernel.integration.agui.state import AGUIState
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.envelope import ATTR_AGUI, ATTR_REQUEST_ID, ATTR_USER_ID, QueueMessage, QueueName
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.dynamodb import DynamoDBResponseStore
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


def _use_mode(monkeypatch, mode):
    """Override one field on the real config, so everything else the code reads stays real."""
    monkeypatch.setattr(AKConfig.get().execution, "mode", mode)


def _use_session_type(monkeypatch, session_type):
    monkeypatch.setattr(AKConfig.get().session, "type", session_type)


def _use_attachment_store(monkeypatch, storage_type, enabled=True):
    monkeypatch.setattr(AKConfig.get().multimodal, "enabled", enabled)
    monkeypatch.setattr(AKConfig.get().multimodal, "storage_type", storage_type)


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore._records.clear()
    InMemoryResponseStore._chunks.clear()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore._records.clear()
    InMemoryResponseStore._chunks.clear()


class _StubRequest:
    """Only `headers` is read once `_resolve_run_inputs` is stubbed out."""

    headers: dict = {}


class _Auth(Authoriser):
    def authorise(self, token):
        return "u1"


class _FakeService:
    def __init__(self, session, agent_name="planner"):
        self.session = session

        class _Agent:
            name = agent_name

        self.agent = _Agent()


class _FakeHandler:
    """Stands in for AgentHandler; `during_run` sees the session the agent would see."""

    def __init__(self, session, chunks, during_run=None):
        self.service = _FakeService(session)
        self._chunks = chunks
        self._during_run = during_run

    def run_stream_sync(self, requests, acting_user_id=None):
        if self._during_run is not None:
            self._during_run(self.service.session)
        yield from self._chunks


class _FakeChatService:
    def __init__(self, session, chunks, during_run=None):
        self._handler = _FakeHandler(session, chunks, during_run)
        self.prepared = []

    def prepare_agent_handler(self, session_id, agent):
        self.prepared.append((session_id, agent))
        return self._handler


def _text_run():
    return [
        StreamChunk(event=MessageStart(message_id="m1")),
        StreamChunk(delta="Hi", event=TextDelta(message_id="m1", content="Hi")),
        StreamChunk(event=MessageEnd(message_id="m1")),
        StreamChunk(done=True),
    ]


def _agui_message(envelope=None, attributes=None, receive_count=1):
    body = AGUIRunRequest(session_id="t-1", agent="planner", user_id="u1", requests=[], agui=envelope)
    return QueueMessage(
        body=body.model_dump_json(exclude_none=True),
        attributes=attributes if attributes is not None else {ATTR_AGUI: "1", ATTR_REQUEST_ID: "r1"},
        group_id="t-1",
        dedup_id="d1",
        receive_count=receive_count,
        message_id="m1",
    )


def _drain_output(transport, limit=20):
    """Chunks of one run share a group, and the transport keeps one in flight per group, so
    they come back one ack at a time rather than in a single fetch."""
    consumer = transport.create_consumer(QueueName.OUTPUT)
    messages = []
    for _ in range(limit):
        batch = consumer.fetch(1, 0.2)
        if not batch:
            break
        messages.append(batch[0])
        consumer.ack(batch[0])
    return messages


RUNNER_CLASSES = [AgentRunner, StreamAgentRunner]


def _run_through_runner(session, chunks, envelope=None, during_run=None, attributes=None, runner_cls=AgentRunner):
    transport = InMemoryTransport()
    chat_service = _FakeChatService(session, chunks, during_run)
    runner_cls(transport=transport, chat_service=chat_service).process(_agui_message(envelope, attributes))
    return _drain_output(transport), chat_service


class TestMarkerDispatchIsStructural:
    """The bypass this guards against was invisible because the tests only built AgentRunner.

    ``RUNNER_CLASSES`` is every class IOHandler can pick from ``execution.mode``; an AG-UI message
    must take the same path through all of them, so these cases run once per entry.

    ``process`` is the dispatcher and must stay the base class's for every runner; a subclass with
    different run behaviour overrides ``_process_run``. An override of ``process`` compiles, passes
    every ordinary test, and silently drops the AG-UI branch for whichever execution mode selects
    that class.
    """

    def test_the_matrix_covers_every_runner_class(self):
        """So a new sibling cannot be added without the cases below being run against it."""
        assert set(RUNNER_CLASSES) == {AgentRunner, *AgentRunner.__subclasses__()}

    @pytest.mark.parametrize("runner_cls", RUNNER_CLASSES)
    def test_no_subclass_overrides_the_dispatcher(self, runner_cls):
        assert runner_cls.process is AgentRunner.process, f"{runner_cls.__name__} must override _process_run, not process"

    @pytest.mark.parametrize("runner_cls", RUNNER_CLASSES)
    def test_the_agui_run_is_identical_whichever_class_was_selected(self, runner_cls):
        """Envelope applied, state snapshot emitted, marker on every output — for both classes."""
        envelope = AGUIRunEnvelope(state={"tasks": []}, forwarded_props={"page": "/x"})
        seen = {}

        def during_run(run_session):
            seen["forwarded_props"] = AGUIState.read_forwarded_props(run_session)
            AGUIState.write_state(run_session, {"tasks": [{"title": "buy milk"}]})

        outputs, chat_service = _run_through_runner(Session("t-1"), _text_run(), envelope=envelope, during_run=during_run, runner_cls=runner_cls)
        bodies = [json.loads(out.body) for out in outputs]

        assert chat_service.prepared == [("t-1", "planner")], "the AG-UI branch was not taken"
        assert seen["forwarded_props"] == {"page": "/x"}
        assert all(ATTR_AGUI in out.attributes for out in outputs)
        assert any("agui_state" in body for body in bodies)
        assert bodies[-1].get("done") is True

    @pytest.mark.parametrize("runner_cls", RUNNER_CLASSES)
    def test_a_permanent_failure_terminates_the_stream(self, runner_cls):
        """Without `done` the edge waits out its whole budget and reports a timeout instead.

        This is the runner's own handler, not the Response Handler's: the two are separate
        methods, and only this one runs when the input message exhausts its retries.
        """
        transport = InMemoryTransport()
        runner_cls(transport=transport, chat_service=_FakeChatService(Session("t-1"), [])).on_permanent_failure(_agui_message())

        outputs = _drain_output(transport)
        assert len(outputs) == 1
        body = json.loads(outputs[0].body)
        assert body["done"] is True, "an AG-UI error chunk without `done` never ends the client's stream"
        assert body["error"]
        assert ATTR_AGUI in outputs[0].attributes


class TestTheMarkerSurvivesTheRunnerHop:
    """Without the allowlist entry the Response Handler never sees the marker (#710 §1-2)."""

    def test_every_output_message_carries_the_marker(self):
        outputs, _ = _run_through_runner(Session("t-1"), _text_run())

        assert outputs, "the runner produced no output messages"
        assert all(ATTR_AGUI in out.attributes for out in outputs)

    def test_the_marker_routes_the_runner_to_the_streaming_path_under_rest_sync(self, monkeypatch):
        """IOHandler picks the runner class from execution.mode; the marker has to beat it."""
        _use_mode(monkeypatch, ExecutionMode.REST_SYNC)
        outputs, _ = _run_through_runner(Session("t-1"), _text_run())

        # One message per event rather than a single assembled reply.
        assert len(outputs) == 4
        assert json.loads(outputs[0].body)["event"]["type"] == "message_start"


class TestTheEnvelopeCrossesTheQueue:
    """forwardedProps and context live in the volatile cache, which no session store persists."""

    def test_the_inbound_values_reach_the_running_session(self):
        seen = {}
        session = Session("t-1")
        envelope = AGUIRunEnvelope(
            state={"tasks": [{"title": "existing"}]},
            forwarded_props={"page": "/dashboard"},
            context=[{"description": "locale", "value": "en-GB"}],
        )

        def during_run(run_session):
            seen["state"] = AGUIState.read_state(run_session)
            seen["forwarded_props"] = AGUIState.read_forwarded_props(run_session)
            seen["context"] = AGUIState.read_context(run_session)

        _run_through_runner(session, _text_run(), envelope=envelope, during_run=during_run)

        assert seen["state"] == {"tasks": [{"title": "existing"}]}
        assert seen["forwarded_props"] == {"page": "/dashboard"}, "forwardedProps did not reach the agent"
        assert seen["context"] == [{"description": "locale", "value": "en-GB"}]

    def test_the_per_run_values_stay_volatile(self):
        """They must not become durable, or the previous turn's context leaks into the next one."""
        session = Session("t-1")
        envelope = AGUIRunEnvelope(state={"a": 1}, forwarded_props={"page": "/x"}, context=[{"description": "d", "value": "v"}])

        _run_through_runner(session, _text_run(), envelope=envelope)

        durable = dict(session.get_all(volatile=False))
        non_volatile = durable["nv_cache"].model_dump() if hasattr(durable.get("nv_cache"), "model_dump") else {}
        assert "agui_state" in json.dumps(non_volatile), "state should be durable"
        assert "agui_forwarded_props" not in json.dumps(non_volatile), "forwardedProps must not be persisted"
        assert "agui_context" not in json.dumps(non_volatile), "context must not be persisted"

    def test_a_run_without_an_envelope_is_unaffected(self):
        outputs, _ = _run_through_runner(Session("t-1"), _text_run(), envelope=None)
        assert len(outputs) == 4


class TestTheStateSnapshot:
    def test_no_snapshot_when_the_agent_changes_nothing(self):
        """The baseline is taken after the envelope is applied, so inbound state is not a change."""
        envelope = AGUIRunEnvelope(state={"tasks": [{"title": "existing"}]})
        outputs, _ = _run_through_runner(Session("t-1"), _text_run(), envelope=envelope)

        assert not any("agui_state" in json.loads(out.body) for out in outputs)

    def test_a_snapshot_is_emitted_when_the_agent_writes_state(self):
        def during_run(session):
            AGUIState.write_state(session, {"tasks": [{"title": "buy milk"}]})

        outputs, _ = _run_through_runner(Session("t-1"), _text_run(), during_run=during_run)
        bodies = [json.loads(out.body) for out in outputs]

        assert any("agui_state" in body for body in bodies)

    def test_the_snapshot_precedes_the_terminal_chunk(self):
        """stream() returns at the first `done`, so a snapshot sent after it is never read."""

        def during_run(session):
            AGUIState.write_state(session, {"tasks": [{"title": "buy milk"}]})

        outputs, _ = _run_through_runner(Session("t-1"), _text_run(), during_run=during_run)
        bodies = [json.loads(out.body) for out in outputs]

        snapshot_at = next(i for i, body in enumerate(bodies) if "agui_state" in body)
        terminal_at = next(i for i, body in enumerate(bodies) if body.get("done"))
        assert snapshot_at < terminal_at


class TestResponseHandlerDispatch:
    """The marker branch runs ahead of the execution.mode branch, so AG-UI never depends on it."""

    @pytest.mark.parametrize("mode", [ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC, ExecutionMode.STREAM, ExecutionMode.ASYNC])
    @pytest.mark.parametrize("user_id_present", [False, True])
    def test_chunks_reach_the_store_whatever_the_mode_or_user_id(self, monkeypatch, mode, user_id_present):
        _use_mode(monkeypatch, mode)

        attributes = {ATTR_AGUI: "1", ATTR_REQUEST_ID: "r1"}
        if user_id_present:
            # The runner injects this from the body on the scheduled-trigger path; it must not
            # divert an AG-UI chunk to the WebSocket push.
            attributes[ATTR_USER_ID] = "u1"

        store = InMemoryResponseStore()
        handler = ResponseHandler(transport=InMemoryTransport(), response_store=store)
        handler.process(QueueMessage(body=json.dumps({"delta": "Hi", "done": True}), attributes=attributes, message_id="m1"))

        assert [chunk for chunk in store.stream("r1", chunk_timeout=2)] == [{"delta": "Hi", "done": True}]

    def test_permanent_failure_writes_one_terminal_chunk(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.REST_SYNC)
        store = InMemoryResponseStore()
        handler = ResponseHandler(transport=InMemoryTransport(), response_store=store)

        handler.on_permanent_failure(QueueMessage(body="{}", attributes={ATTR_AGUI: "1", ATTR_REQUEST_ID: "r1"}, message_id="m1"))

        chunks = [chunk for chunk in store.stream("r1", chunk_timeout=2)]
        assert len(chunks) == 1 and chunks[0]["done"] is True and chunks[0]["error"]

    def test_an_unmarked_message_is_untouched(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.REST_SYNC)
        store = InMemoryResponseStore()
        handler = ResponseHandler(transport=InMemoryTransport(), response_store=store)

        handler.process(QueueMessage(body=json.dumps({"result": "hi"}), attributes={ATTR_REQUEST_ID: "r1", "status_code": "200"}, message_id="m1"))

        assert store.get_record("r1")["body"] == {"result": "hi"}


class TestTheEnvelopeBudget:
    """The budget belongs to the queue hop, not to the protocol (PR #755 review).

    ``build`` is shared with the direct handler, which puts the envelope on nothing, so charging
    the budget there would start rejecting large-state requests that work today.
    """

    class _Input:
        """The three fields `build` reads off a RunAgentInput."""

        def __init__(self, state):
            self.state = state
            self.forwarded_props = None
            self.context = []

    def _oversized(self):
        return AGUIRunEnvelope.build(self._Input({"blob": "x" * (AGUIRunEnvelope.BUDGET_BYTES + 1)}))

    def test_building_an_oversized_envelope_is_not_an_error(self):
        assert self._oversized().state is not None

    def test_the_enqueueing_handler_rejects_it_with_a_400_naming_the_budget(self):
        with pytest.raises(HTTPException) as excinfo:
            self._oversized().reject_if_oversized()

        assert excinfo.value.status_code == 400
        assert str(AGUIRunEnvelope.BUDGET_BYTES) in excinfo.value.detail

    def test_an_envelope_within_budget_passes(self):
        AGUIRunEnvelope.build(self._Input({"tasks": []})).reject_if_oversized()


class TestTheEdgeNeverBlocksTheEventLoop:
    """The edge holds the caller's SSE socket, so a blocking call there stalls every request.

    Both calls reach a network service with no async client: the broker send and, on a redis-like
    store, close_stream's round trips. The shared driver retries a dead connection three times with
    two-second gaps, so an outage is tens of seconds of a frozen uvicorn worker rather than one slow
    request. `pipeline/request_handler.py` offloads the identical send and says why.
    """

    class _RecordingProducer:
        def __init__(self):
            self.threads = []

        def enqueue(self, *args, **kwargs):
            self.threads.append(threading.current_thread())
            return {}

    class _RunInput:
        thread_id = "t-1"
        run_id = "r-1"
        parent_run_id = None
        state = None
        forwarded_props = None
        context = []

    def _handler(self, monkeypatch):
        handler = TestPreconditions._construct(InMemoryResponseStore(), "in_memory")
        agent = type("_Agent", (), {"name": "planner"})()

        async def _resolved(agent_name, request):
            return "u1", agent, self._RunInput(), []

        monkeypatch.setattr(handler, "_resolve_run_inputs", _resolved)
        monkeypatch.setattr(handler, "_warn_if_unreadable", lambda *a, **k: None)
        return handler

    @pytest.mark.asyncio
    async def test_the_enqueue_runs_off_the_event_loop(self, monkeypatch):
        handler = self._handler(monkeypatch)
        producer = self._RecordingProducer()
        handler._producer = producer

        await handler._run("planner", _StubRequest())

        assert producer.threads, "the producer was never called"
        assert producer.threads[0] is not threading.current_thread(), "the broker send ran on the event loop"

    @pytest.mark.asyncio
    async def test_close_stream_runs_off_the_event_loop(self, monkeypatch):
        """Including on the disconnect path, which is the only reason close_stream exists."""
        handler = self._handler(monkeypatch)
        handler._producer = self._RecordingProducer()
        threads = []

        class _Store(InMemoryResponseStore):
            def stream(self, request_id, chunk_timeout=None):
                yield {"done": True}

            def close_stream(self, request_id):
                threads.append(threading.current_thread())

        handler._store = _Store()
        response = await handler._run("planner", _StubRequest())
        async for _ in response.body_iterator:
            pass

        assert threads, "close_stream was never called"
        assert threads[0] is not threading.current_thread(), "close_stream ran on the event loop"


class TestPreconditions:
    """Capability alone is not enough: the in-memory store streams chunks and is process-local."""

    @staticmethod
    def _construct(store, transport):
        class _Factory:
            @staticmethod
            def create(*a, **k):
                return store

        class _Transport:
            @staticmethod
            def resolve_type():
                return transport

        with patch.multiple("agentkernel.integration.agui.pipeline", ResponseStoreFactory=_Factory, QueueTransportFactory=_Transport):
            return AGUIPipelineRequestHandler(authoriser=_Auth())

    def test_a_store_that_cannot_stream_chunks_is_refused(self):
        store = DynamoDBResponseStore.__new__(DynamoDBResponseStore)
        with pytest.raises(AKConfigError, match="cannot stream"):
            self._construct(store, "sqs")

    def test_a_process_local_store_is_refused_on_a_broker(self):
        """The decisive case: capability is True, sharedness is False, and only the second catches it."""
        store = InMemoryResponseStore()
        assert store.supports_chunk_streaming() is True, "capability alone would have let this through"
        assert store.shared is False

        with pytest.raises(AKConfigError, match="process-local"):
            self._construct(store, "sqs")

    def test_the_same_store_is_accepted_on_the_single_process_transport(self):
        handler = self._construct(InMemoryResponseStore(), "in_memory")
        assert handler.requires_pipeline is True

    def test_an_in_memory_session_store_is_refused_on_a_broker(self, monkeypatch):
        class _Shared(InMemoryResponseStore):
            @property
            def shared(self):
                return True

        _use_session_type(monkeypatch, "in_memory")
        with pytest.raises(AKConfigError, match="single-process only"):
            self._construct(_Shared(), "sqs")

    def test_a_process_local_attachment_store_is_refused_on_a_broker(self, monkeypatch):
        """The edge offloads the bytes and the runner resolves the id, so both need the store.

        Nothing fails at startup without this check: the mismatch only surfaces as a per-request
        error, on the requests that carry an attachment.
        """

        class _Shared(InMemoryResponseStore):
            @property
            def shared(self):
                return True

        _use_session_type(monkeypatch, "redis")
        _use_attachment_store(monkeypatch, "in_memory")
        with pytest.raises(AKConfigError, match="keeps attachments in the process"):
            self._construct(_Shared(), "sqs")

    def test_a_shared_attachment_store_is_accepted_on_a_broker(self, monkeypatch):
        class _Shared(InMemoryResponseStore):
            @property
            def shared(self):
                return True

        _use_session_type(monkeypatch, "redis")
        _use_attachment_store(monkeypatch, "dynamodb")
        assert self._construct(_Shared(), "sqs") is not None

    def test_the_attachment_store_is_not_checked_when_multimodal_is_off(self, monkeypatch):
        """Attachments are refused outright before they reach a store, so the store is moot."""

        class _Shared(InMemoryResponseStore):
            @property
            def shared(self):
                return True

        _use_session_type(monkeypatch, "redis")
        _use_attachment_store(monkeypatch, "in_memory", enabled=False)
        assert self._construct(_Shared(), "sqs") is not None

    def test_a_dotted_path_session_store_is_left_alone(self, monkeypatch):
        """The accepted blind spot (#710 §6): the check proves the literal name, nothing more."""

        class _Shared(InMemoryResponseStore):
            @property
            def shared(self):
                return True

        _use_session_type(monkeypatch, "mycompany.stores.CustomSessionStore")
        assert self._construct(_Shared(), "sqs") is not None
