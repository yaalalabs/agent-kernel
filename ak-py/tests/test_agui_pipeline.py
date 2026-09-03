"""
Tests for queue-mode AG-UI (spec #524 §10, design §15, `integration/agui/pipeline.py`).

Reuses `test_agui_handler.py`'s harness deliberately: the point of extracting `_prepare` is that
the two handlers resolve a run identically, so the same fixtures must drive both.

Four of these guard failures with no other symptom:

- **The session is stored before the enqueue.** The runner loads it in another process, so a
  handler that skipped the store would lose the client's inbound `state` and `forwardedProps`
  silently — the run would still succeed, just without the data.
- **Exactly one terminal event.** A client waits on `RunFinished`/`RunError`; a path that yields
  neither, or both, hangs it or corrupts its state machine. Every failure route is asserted.
- **`close_stream` on every exit.** Without it a Redis reader stays parked and the chunk key
  survives to its TTL, so an abandoned run leaks per-request state.
- **The runner streams on the marker, not the mode.** `mode: rest_sync` is the default, and under
  it the plain `AgentRunner` would otherwise produce one lump reply with no typed events — AG-UI
  would appear to work and emit nothing but `RunStarted`/`RunFinished`.
"""

import json
from contextlib import contextmanager
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.core.config import _AGUIConfig, _GuardrailConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta, ToolCallStart
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.factory import AKConfigError
from agentkernel.integration.agui import AGUIPipelineRequestHandler
from agentkernel.integration.agui.state import AGUI_STATE_KEY
from agentkernel.pipeline.envelope import ATTR_AGUI, ATTR_REQUEST_ID, QueueMessage, QueueName
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

from test_agui_handler import AUTH, ScriptedAgent, StaticAuthoriser, body, events, types_of

TEXT_SCRIPT = [MessageStart(message_id="m1"), TextDelta(message_id="m1", content="hi"), MessageEnd(message_id="m1")]


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()


class _NoStreamStore(InMemoryResponseStore):
    """A store without the chunk-streaming capability — every shared store today, before #524."""

    def supports_chunk_streaming(self) -> bool:
        return False


def _install_cfg(monkeypatch, agui_cfg=None, session_type="in_memory", transport_type="in_memory"):
    """Point AKConfig.get() at a stub carrying every section this path reads."""

    resolved_agui = agui_cfg if agui_cfg is not None else _AGUIConfig()

    class _Cfg:
        agui = resolved_agui
        multimodal = None
        sandbox = None
        guardrail = _GuardrailConfig()

        class session:
            type = session_type

        class execution:
            # The chunk-streaming stores read this for their default wait budget; keep it short
            # so a genuinely stuck drain fails the test instead of hanging the suite.
            class response_store:
                retry_count = 2
                delay = 1.0

            class queues:
                class output:
                    max_receive_count = 3

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
    monkeypatch.setattr(
        "agentkernel.pipeline.transport.base.QueueTransportFactory.resolve_type",
        classmethod(lambda cls: transport_type),
    )


@contextmanager
def serving(monkeypatch, agents, agui_cfg=None, store=None, response_store=None, transport=None, session_type="in_memory"):
    """Mount the queue-mode AG-UI router over a runtime holding the given agents."""
    _install_cfg(monkeypatch, agui_cfg, session_type=session_type)
    Runtime._system_pre_hooks = []
    Runtime._system_post_hooks = []
    runtime = Runtime(store if store is not None else InMemorySessionStore())
    for agent in agents:
        runtime.register(agent)
    try:
        with runtime:
            handler = AGUIPipelineRequestHandler(
                authoriser=StaticAuthoriser(),
                transport=transport if transport is not None else InMemoryTransport(),
                response_store=response_store if response_store is not None else InMemoryResponseStore(),
            )
            app = FastAPI()
            app.include_router(handler.get_router())
            yield TestClient(app), runtime, handler
    finally:
        Runtime._system_pre_hooks = None
        Runtime._system_post_hooks = None


def _input_messages(transport, n=10):
    return transport.create_consumer(QueueName.INPUT).fetch(n, 0.5)


def _seed(store, request_id, *chunks):
    """Pre-load a run's chunks so the edge's drain completes without a live runner."""
    for chunk in chunks:
        store.add_chunk(request_id, chunk)


def _enqueued_request_id(transport) -> str:
    messages = _input_messages(transport)
    assert len(messages) == 1
    return messages[0].attributes[ATTR_REQUEST_ID]


class TestConstruction:
    def test_it_declares_requires_pipeline(self):
        # Without this a bare RESTAPI.run([...]) app would enqueue into a queue no runner drains
        # while the client held its SSE connection open (design Q9).
        assert AGUIPipelineRequestHandler.requires_pipeline is True

    def test_the_direct_handler_still_does_not(self):
        from agentkernel.integration.agui import AGUIRequestHandler

        assert AGUIRequestHandler.requires_pipeline is False

    def test_it_rejects_a_response_store_that_cannot_stream_chunks(self, monkeypatch):
        _install_cfg(monkeypatch)
        with Runtime(InMemorySessionStore()):
            with pytest.raises(AKConfigError, match="chunk-streaming response store"):
                AGUIPipelineRequestHandler(
                    authoriser=StaticAuthoriser(), transport=InMemoryTransport(), response_store=_NoStreamStore()
                )

    def test_the_rejection_names_the_configured_store(self, monkeypatch):
        _install_cfg(monkeypatch)
        with Runtime(InMemorySessionStore()):
            with pytest.raises(AKConfigError, match="_NoStreamStore"):
                AGUIPipelineRequestHandler(
                    authoriser=StaticAuthoriser(), transport=InMemoryTransport(), response_store=_NoStreamStore()
                )

    def test_it_rejects_an_in_memory_session_store_on_a_broker_transport(self, monkeypatch):
        # The accidental default: session.type defaults to in_memory, and over a broker the runner
        # would load a session this process never shared.
        _install_cfg(monkeypatch, session_type="in_memory", transport_type="sqs")
        with Runtime(InMemorySessionStore()):
            with pytest.raises(AKConfigError, match="shared session store"):
                AGUIPipelineRequestHandler(
                    authoriser=StaticAuthoriser(), transport=InMemoryTransport(), response_store=InMemoryResponseStore()
                )

    def test_an_in_memory_session_store_is_fine_in_the_single_process_topology(self, monkeypatch):
        _install_cfg(monkeypatch, session_type="in_memory", transport_type="in_memory")
        with Runtime(InMemorySessionStore()):
            AGUIPipelineRequestHandler(
                authoriser=StaticAuthoriser(), transport=InMemoryTransport(), response_store=InMemoryResponseStore()
            )

    def test_a_shared_session_store_is_accepted_on_a_broker_transport(self, monkeypatch):
        _install_cfg(monkeypatch, session_type="redis", transport_type="sqs")
        with Runtime(InMemorySessionStore()):
            AGUIPipelineRequestHandler(
                authoriser=StaticAuthoriser(), transport=InMemoryTransport(), response_store=InMemoryResponseStore()
            )


class TestTheEdge:
    def test_the_run_is_enqueued_with_the_agui_marker(self, monkeypatch):
        transport = InMemoryTransport()
        store = InMemoryResponseStore()
        with serving(monkeypatch, [ScriptedAgent()], transport=transport, response_store=store) as (client, _, _h):
            _seed(store, "unused", {"done": True})
            client.post("/agui/assistant", json=body(), headers=AUTH)

        messages = _input_messages(transport)
        assert len(messages) == 1
        assert messages[0].attributes[ATTR_AGUI] == "1"

    def test_the_queue_envelope_carries_the_ordering_and_dedup_keys(self, monkeypatch):
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent()], transport=transport) as (client, _, _h):
            client.post("/agui/assistant", json=body(threadId="t-42"), headers=AUTH)

        message = _input_messages(transport)[0]
        # group_id is the thread, so one conversation stays ordered; dedup_id is the run's own id.
        assert message.group_id == "t-42"
        assert message.dedup_id == message.attributes[ATTR_REQUEST_ID]

    def test_no_user_id_attribute_is_stamped(self, monkeypatch):
        # user_id is the WebSocket-entered marker; AG-UI is not that, so it travels in the body.
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent()], transport=transport) as (client, _, _h):
            client.post("/agui/assistant", json=body(), headers=AUTH)

        message = _input_messages(transport)[0]
        assert "user_id" not in message.attributes
        assert json.loads(message.body)["user_id"] == "u1"

    def test_the_body_carries_a_prebuilt_request_list_and_an_empty_prompt(self, monkeypatch):
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent()], transport=transport) as (client, _, _h):
            client.post("/agui/assistant", json=body(), headers=AUTH)

        sent = json.loads(_input_messages(transport)[0].body)
        assert sent["requests"] == [{"type": "text", "prompt": "hello"}]
        # Legal: ChatService._validate requires a prompt only when `requests` is None.
        assert sent.get("prompt", "") == ""
        assert sent["session_id"] == "session-1"

    def test_the_resolved_agent_name_is_sent_not_the_path_string(self, monkeypatch):
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent(name="assistant")], transport=transport) as (client, _, _h):
            client.post("/agui/assistant", json=body(), headers=AUTH)

        assert json.loads(_input_messages(transport)[0].body)["agent"] == "assistant"

    def test_the_session_is_stored_before_the_run_is_enqueued(self, monkeypatch):
        # The runner reads the client's state from the shared store, so it has to be there first.
        order: list[str] = []

        class RecordingSessionStore(InMemorySessionStore):
            def store(self, session):
                order.append("store")
                return super().store(session)

        class RecordingTransport(InMemoryTransport):
            def send(self, queue, message):
                order.append("enqueue")
                return super().send(queue, message)

        with serving(
            monkeypatch, [ScriptedAgent()], store=RecordingSessionStore(), transport=RecordingTransport()
        ) as (client, _, _h):
            client.post("/agui/assistant", json=body(state={"city": "Colombo"}), headers=AUTH)

        # Session preparation stores once on its own, so the count is not the invariant: what
        # matters is that every session write lands before the run is enqueued, or the runner
        # could load the session before the client's state was on it.
        assert order[-1] == "enqueue"
        assert order.count("enqueue") == 1
        assert "store" in order[:-1]

    def test_the_client_state_is_on_the_stored_session(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, runtime, _h):
            client.post("/agui/assistant", json=body(state={"city": "Colombo"}), headers=AUTH)
            session = runtime.sessions().load("session-1")

        assert session.get_non_volatile_cache().get(AGUI_STATE_KEY) == {"city": "Colombo"}

    def test_nothing_is_enqueued_when_the_agent_is_unknown(self, monkeypatch):
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent()], transport=transport) as (client, _, _h):
            response = client.post("/agui/nope", json=body(), headers=AUTH)

        assert response.status_code == 404
        assert _input_messages(transport) == []

    def test_nothing_is_enqueued_without_a_valid_token(self, monkeypatch):
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent()], transport=transport) as (client, _, _h):
            response = client.post("/agui/assistant", json=body(), headers={"Authorization": "Bearer nope"})

        assert response.status_code == 401
        assert _input_messages(transport) == []

    def test_nothing_is_enqueued_for_a_body_with_no_user_message(self, monkeypatch):
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent()], transport=transport) as (client, _, _h):
            response = client.post("/agui/assistant", json=body(messages=[]), headers=AUTH)

        assert response.status_code == 400
        assert _input_messages(transport) == []

    def test_a_non_streaming_agent_is_still_rejected_with_400(self, monkeypatch):
        transport = InMemoryTransport()
        with serving(monkeypatch, [ScriptedAgent(streaming=False)], transport=transport) as (client, _, _h):
            response = client.post("/agui/assistant", json=body(), headers=AUTH)

        assert response.status_code == 400
        assert _input_messages(transport) == []


class TestTheDrain:
    """The edge's generator, fed from the response store the way the Response Handler feeds it."""

    def _run_with(self, monkeypatch, *chunks, agents=None):
        """POST a run, seed the store under the id the edge minted, and read the SSE body back.

        The store is seeded *before* the request so the drain never blocks: the edge mints its own
        request_id, so the seeding is done through a transport that reports it synchronously.
        """
        transport = InMemoryTransport()
        store = InMemoryResponseStore()
        seeded: dict = {}

        class SeedingTransport(InMemoryTransport):
            def send(self, queue, message):
                result = super().send(queue, message)
                request_id = message.attributes[ATTR_REQUEST_ID]
                seeded["request_id"] = request_id
                for chunk in chunks:
                    store.add_chunk(request_id, chunk)
                return result

        with serving(
            monkeypatch, agents or [ScriptedAgent()], transport=SeedingTransport(), response_store=store
        ) as (client, _, handler):
            response = client.post("/agui/assistant", json=body(), headers=AUTH)
        return response, seeded.get("request_id"), store

    def _chunk(self, event):
        return {"event": event.model_dump(), "done": False}

    def test_a_clean_run_brackets_the_events(self, monkeypatch):
        response, _, _ = self._run_with(
            monkeypatch,
            self._chunk(MessageStart(message_id="m1")),
            self._chunk(TextDelta(message_id="m1", content="hi")),
            self._chunk(MessageEnd(message_id="m1")),
            {"done": True},
        )

        assert types_of(response) == [
            "RUN_STARTED",
            "TEXT_MESSAGE_START",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
            "RUN_FINISHED",
        ]

    def test_typed_events_survive_the_queue_and_reach_the_mapper(self, monkeypatch):
        response, _, _ = self._run_with(
            monkeypatch,
            self._chunk(TextDelta(message_id="m1", content="hello")),
            {"done": True},
        )

        content = [event for event in events(response) if event["type"] == "TEXT_MESSAGE_CONTENT"]
        assert content[0]["delta"] == "hello"

    def test_a_tool_call_maps_through(self, monkeypatch):
        response, _, _ = self._run_with(
            monkeypatch,
            self._chunk(ToolCallStart(tool_call_id="tc1", name="weather")),
            {"done": True},
        )

        assert "TOOL_CALL_START" in types_of(response)

    def test_a_state_chunk_becomes_one_state_snapshot(self, monkeypatch):
        response, _, _ = self._run_with(
            monkeypatch,
            self._chunk(TextDelta(message_id="m1", content="hi")),
            {"agui_state": {"city": "Kandy"}},
            {"done": True},
        )

        kinds = types_of(response)
        assert kinds.count("STATE_SNAPSHOT") == 1
        snapshot = next(event for event in events(response) if event["type"] == "STATE_SNAPSHOT")
        assert snapshot["snapshot"] == {"city": "Kandy"}
        # After the content, before the terminal event.
        assert kinds.index("STATE_SNAPSHOT") > kinds.index("TEXT_MESSAGE_CONTENT")
        assert kinds.index("STATE_SNAPSHOT") < kinds.index("RUN_FINISHED")

    def test_no_state_chunk_means_no_snapshot(self, monkeypatch):
        response, _, _ = self._run_with(monkeypatch, self._chunk(TextDelta(message_id="m1", content="hi")), {"done": True})

        assert "STATE_SNAPSHOT" not in types_of(response)

    def test_a_bare_delta_chunk_yields_nothing(self, monkeypatch):
        # AG-UI's content comes from the typed events; a delta without one has no equivalent.
        response, _, _ = self._run_with(monkeypatch, {"delta": "hi"}, {"done": True})

        assert types_of(response) == ["RUN_STARTED", "RUN_FINISHED"]

    def test_an_event_with_no_agui_equivalent_is_dropped_silently(self, monkeypatch):
        response, _, _ = self._run_with(
            monkeypatch,
            {"event": {"type": "run_start", "run_id": "x"}, "done": False},
            {"done": True},
        )

        assert types_of(response) == ["RUN_STARTED", "RUN_FINISHED"]

    def test_an_error_chunk_becomes_exactly_one_run_error(self, monkeypatch):
        response, _, _ = self._run_with(monkeypatch, {"error": "the agent exploded", "done": True})

        kinds = types_of(response)
        assert kinds == ["RUN_STARTED", "RUN_ERROR"]
        assert "RUN_FINISHED" not in kinds
        assert events(response)[-1]["message"] == "the agent exploded"

    def test_an_error_after_content_still_ends_with_one_run_error(self, monkeypatch):
        response, _, _ = self._run_with(
            monkeypatch,
            self._chunk(TextDelta(message_id="m1", content="par")),
            {"error": "died mid-run", "done": True},
        )

        kinds = types_of(response)
        assert kinds[-1] == "RUN_ERROR"
        assert kinds.count("RUN_ERROR") == 1
        assert "RUN_FINISHED" not in kinds

    def test_an_unparsable_chunk_is_discarded_without_killing_the_run(self, monkeypatch):
        response, _, _ = self._run_with(
            monkeypatch,
            {"event": "not-an-object"},
            self._chunk(TextDelta(message_id="m1", content="hi")),
            {"done": True},
        )

        kinds = types_of(response)
        assert kinds[-1] == "RUN_FINISHED"
        assert "TEXT_MESSAGE_CONTENT" in kinds

    def test_the_chunk_state_is_released_when_the_run_ends(self, monkeypatch):
        _response, request_id, store = self._run_with(monkeypatch, {"done": True})

        # close_stream ran in the generator's finally: nothing is left parked or buffered.
        assert request_id is not None
        assert store._chunks.get(request_id) is None

    def test_the_chunk_state_is_released_after_an_error_too(self, monkeypatch):
        _response, request_id, store = self._run_with(monkeypatch, {"error": "boom", "done": True})

        assert store._chunks.get(request_id) is None


class TestResponseHandlerRouting:
    """The other half of the return path: an output message with the marker goes to the store."""

    def _handler(self, store):
        from agentkernel.pipeline.response_handler import ResponseHandler

        return ResponseHandler(transport=InMemoryTransport(), response_store=store)

    def _output_msg(self, body_dict, attributes):
        return QueueMessage(body=json.dumps(body_dict), attributes=attributes, group_id="s1", message_id="m1")

    @pytest.mark.parametrize("mode", ["rest_sync", "stream", "async"])
    def test_an_agui_chunk_reaches_the_store_under_every_mode(self, monkeypatch, mode):
        from agentkernel.core.model import ExecutionMode

        resolved_mode = ExecutionMode(mode)

        class _Cfg:
            class execution:
                mode = resolved_mode

                class queues:
                    class output:
                        max_receive_count = 3

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        store = InMemoryResponseStore()
        self._handler(store).process(
            self._output_msg({"delta": "hi"}, {ATTR_REQUEST_ID: "r1", ATTR_AGUI: "1"})
        )

        assert store._chunks["r1"].get_nowait() == {"delta": "hi"}

    def test_a_permanent_failure_becomes_one_error_chunk(self, monkeypatch):
        from agentkernel.core.model import ExecutionMode

        class _Cfg:
            class execution:
                mode = ExecutionMode.REST_SYNC

                class queues:
                    class output:
                        max_receive_count = 3

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        store = InMemoryResponseStore()
        self._handler(store).on_permanent_failure(
            self._output_msg({"delta": "hi"}, {ATTR_REQUEST_ID: "r1", ATTR_AGUI: "1"})
        )

        chunk = store._chunks["r1"].get_nowait()
        assert chunk["done"] is True
        assert "after 3 retries" in chunk["error"]
