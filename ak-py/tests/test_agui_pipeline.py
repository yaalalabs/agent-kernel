"""AG-UI over the queue pipeline (spec #710).

The four cases that carry the design are the ones that fail against the version of it that went
to review: a response store's chunk-streaming capability says nothing about whether another
process can read it; the marker has to survive the runner hop or the Response Handler never sees
it; the client's forwardedProps and context cannot cross on the session; and the state baseline
has to be taken after the inbound state is applied, not before.
"""

import json
from unittest.mock import patch

import pytest

from agentkernel.auth.authoriser import Authoriser
from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import ExecutionMode, StreamChunk
from agentkernel.core.util.factory import AKConfigError
from agentkernel.integration.agui.pipeline import AGUIPipelineRequestHandler
from agentkernel.integration.agui.run_input import AGUIRunEnvelope, AGUIRunRequest
from agentkernel.integration.agui.state import AGUIState
from agentkernel.pipeline.agent_runner import AgentRunner
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


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore._records.clear()
    InMemoryResponseStore._chunks.clear()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore._records.clear()
    InMemoryResponseStore._chunks.clear()


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


def _run_through_runner(session, chunks, envelope=None, during_run=None, attributes=None):
    transport = InMemoryTransport()
    chat_service = _FakeChatService(session, chunks, during_run)
    AgentRunner(transport=transport, chat_service=chat_service).process(_agui_message(envelope, attributes))
    return _drain_output(transport), chat_service


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

    def test_a_dotted_path_session_store_is_left_alone(self, monkeypatch):
        """The accepted blind spot (#710 §6): the check proves the literal name, nothing more."""

        class _Shared(InMemoryResponseStore):
            @property
            def shared(self):
                return True

        _use_session_type(monkeypatch, "mycompany.stores.CustomSessionStore")
        assert self._construct(_Shared(), "sqs") is not None
