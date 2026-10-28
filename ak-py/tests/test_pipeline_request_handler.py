import json
import threading

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import AgentReplyText, AgentRequestText, BaseRunRequest
from agentkernel.core.runtime import Runtime
from agentkernel.pipeline import request_handler
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.consumer import ConsumerLoop
from agentkernel.pipeline.envelope import ATTR_PROTOCOL, QueueName
from agentkernel.pipeline.request_handler import QueuedReply, ReplyTimeoutError, RequestHandler, RestHandler
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.factory import ResponseStoreFactory
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

AGENT_NAME = "pipeline-e2e-agent"


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        if prompt == "boom":
            raise RuntimeError("agent exploded")
        return AgentReplyText(response=f"ok:{prompt}")

    async def stream(self, agent, session, requests):
        # A runner owns its own boundaries. The frame assertions below are unchanged: the boundaries
        # are emitted here rather than synthesised downstream, which does not alter the wire.
        yield MessageStart(message_id="m-1")
        for token in ["he", "llo"]:
            yield TextDelta(message_id="m-1", content=token)
        yield MessageEnd(message_id="m-1")


class DummyAgent(Agent):
    def __init__(self):
        super().__init__(AGENT_NAME, DummyRunner("DummyRunner"))

    def get_description(self) -> str:
        return "Pipeline e2e test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    ThreadRunner.shutdown_event.clear()
    AKConfig._reset()


@pytest.fixture
def dummy_agent():
    agent = DummyAgent()
    Runtime.current().register(agent)
    yield agent
    Runtime.current().deregister(agent)


def _configure(monkeypatch, mode=None):
    """Point AKConfig at real defaults (in_memory transport) with a fast response-wait budget."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    if mode:
        monkeypatch.setenv("AK_EXECUTION__MODE", mode)
    else:
        monkeypatch.delenv("AK_EXECUTION__MODE", raising=False)
    monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT", "100")
    monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__DELAY", "0.05")
    AKConfig._reset()


@pytest.fixture
def workers():
    """Run the Agent Runner and Response Handler consumer loops on daemon threads."""
    threads = []

    def start(stream: bool = False):
        transport = InMemoryTransport()
        runner = StreamAgentRunner(transport=transport) if stream else AgentRunner(transport=transport)
        responder = ResponseHandler(transport=transport)
        loops = [
            ConsumerLoop(
                process=runner.process,
                on_permanent_failure=runner.on_permanent_failure,
                max_receive_count=3,
                num_consumers=1,
                batch_size=10,
                consumer_factory=lambda: transport.create_consumer(QueueName.INPUT),
                thread_name_prefix="e2e-runner",
                wait_seconds=0.05,
            ),
            ConsumerLoop(
                process=responder.process,
                on_permanent_failure=responder.on_permanent_failure,
                max_receive_count=3,
                num_consumers=1,
                batch_size=10,
                consumer_factory=lambda: transport.create_consumer(QueueName.OUTPUT),
                thread_name_prefix="e2e-responder",
                wait_seconds=0.05,
            ),
        ]
        for loop in loops:
            thread = threading.Thread(target=loop._consumer_loop, daemon=True)
            thread.start()
            threads.append(thread)

    yield start

    ThreadRunner.shutdown_event.set()
    for thread in threads:
        thread.join(timeout=2)


def _client() -> TestClient:
    handler = RequestHandler()
    app = FastAPI()
    app.include_router(handler.get_router())
    return TestClient(app)


CHAT = RequestHandler.CHAT_PATH


class TestRestSyncParity:
    def test_rest_sync_success(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode="rest_sync")
        workers()
        response = _client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME})
        assert response.status_code == 200
        assert response.json() == {"result": "ok:hello", "session_id": "s1"}

    def test_mode_unset_behaves_as_rest_sync(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode=None)
        workers()
        response = _client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME})
        assert response.status_code == 200
        assert response.json() == {"result": "ok:hello", "session_id": "s1"}

    def test_agent_error_maps_to_http_500_with_direct_mode_shape(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode="rest_sync")
        workers()
        response = _client().post(CHAT, json={"prompt": "boom", "session_id": "s1", "agent": AGENT_NAME})
        assert response.status_code == 500
        assert response.json()["detail"] == {"error": "agent exploded", "session_id": "s1"}

    def test_missing_session_id_maps_to_direct_mode_400(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_sync")
        response = _client().post(CHAT, json={"prompt": "hello"})
        assert response.status_code == 400
        assert response.json()["detail"] == {"error": "No session_id is provided in the request"}

    def test_agents_route_lists_registered_agents(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_sync")
        response = _client().get(RequestHandler.AGENTS_PATH)
        assert AGENT_NAME in response.json()["agents"]


class TestRestAsync:
    def test_accept_then_poll(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode="rest_async")
        workers()
        client = _client()

        accepted = client.post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME}).json()
        assert accepted["status"] == "ACCEPTED"
        request_id = accepted["request_id"]

        polled = client.get(CHAT, params={"request_id": request_id, "session_id": "s1"})
        assert polled.status_code == 200
        assert polled.json() == {"result": "ok:hello", "session_id": "s1"}

        # get_and_delete semantics: a second poll no longer finds the record.
        assert client.get(CHAT, params={"request_id": request_id}).status_code == 404


class TestStreamSSE:
    def test_stream_yields_sse_chunks(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode="stream")
        workers(stream=True)

        with _client().stream("POST", CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            frames = [json.loads(line[len("data: ") :]) for line in response.iter_lines() if line.startswith("data: ")]

        # Exact direct-mode wire shape (ResponseBuilder.stream_chunk with exclude_none):
        # delta frames carry done=False, the terminal frame done=True. Each also carries the event
        # it was projected from, and the assistant message is bracketed by boundary frames that
        # carry no delta at all. Here Runtime.stream synthesises the boundaries because DummyRunner
        # still yields str; once adapters emit events they supply their own, so the frame count is
        # the same either way.
        message_id = frames[0]["event"]["message_id"]
        assert frames[0] == {
            "event": {"type": "message_start", "message_id": message_id, "role": "assistant"},
            "done": False,
            "session_id": "s1",
        }
        assert frames[1] == {
            "delta": "he",
            "event": {"type": "text_delta", "message_id": message_id, "content": "he"},
            "done": False,
            "session_id": "s1",
        }
        assert frames[2] == {
            "delta": "llo",
            "event": {"type": "text_delta", "message_id": message_id, "content": "llo"},
            "done": False,
            "session_id": "s1",
        }
        assert frames[3] == {"event": {"type": "message_end", "message_id": message_id}, "done": False, "session_id": "s1"}
        assert frames[-1]["done"] is True
        assert frames[-1]["session_id"] == "s1"


class TestStatusHonoringResponses:
    """The stored status_code decides the HTTP response, on every queue-backed REST surface
    (#629 Phase 2): >= 400 raises, a 2xx-non-200 (the 202 of a deferred chat) is preserved, and a
    record without a status_code stays 200.
    """

    def test_status_honoring_lives_in_the_shared_base(self):
        """ECSQueueRequestHandler is a bare RestHandler, so the behavior has to be inherited, not
        re-implemented on the pipeline handler."""
        assert RequestHandler._build_sync_response is RestHandler._build_sync_response

    def test_2xx_non_200_is_preserved(self, monkeypatch):
        _configure(monkeypatch, mode="rest_sync")
        record = {"request_id": "r1", "status_code": 202, "body": {"status": "SCHEDULED", "session_id": "s1"}}

        response = RequestHandler()._build_sync_response(record)

        assert isinstance(response, Response)
        assert response.status_code == 202
        assert response.media_type == "application/json"
        assert json.loads(response.body) == {"status": "SCHEDULED", "session_id": "s1"}

    def test_2xx_non_200_body_survives_a_value_json_response_would_reject(self, monkeypatch):
        """Why this path builds a plain `Response` instead of a `JSONResponse`.

        `JSONResponse` encodes with ``allow_nan=False`` and raises on a non-finite float, where
        FastAPI's own return path — the 200 case two tests down — writes it through. A `NaN`
        reaches a stored record the ordinary way: stdlib ``json.dumps`` writes the token ``NaN``
        onto the queue and ``json.loads`` reads it back as a float, so the two REST surfaces would
        disagree about the same record.
        """
        _configure(monkeypatch, mode="rest_sync")
        record = {"request_id": "r1", "status_code": 202, "body": json.loads(json.dumps({"avg": float("nan")}))}

        with pytest.raises(ValueError, match="not JSON compliant"):
            JSONResponse(content=record["body"])

        response = RequestHandler()._build_sync_response(record)

        assert response.status_code == 202
        assert response.body == b'{"avg": NaN}'

    def test_200_returns_the_bare_body(self, monkeypatch):
        _configure(monkeypatch, mode="rest_sync")
        record = {"request_id": "r1", "status_code": 200, "body": {"result": "ok", "session_id": "s1"}}

        assert RequestHandler()._build_sync_response(record) == {"result": "ok", "session_id": "s1"}

    def test_missing_status_code_defaults_to_200(self, monkeypatch):
        """Records stored before the status was forwarded keep their pre-change behavior."""
        _configure(monkeypatch, mode="rest_sync")

        assert RequestHandler()._build_sync_response({"request_id": "r1", "body": {"result": "ok"}}) == {"result": "ok"}

    def test_error_status_raises_with_the_body_as_detail(self, monkeypatch):
        _configure(monkeypatch, mode="rest_sync")
        record = {"request_id": "r1", "status_code": 400, "body": {"error": "No prompt provided in the request"}}

        with pytest.raises(HTTPException) as raised:
            RequestHandler()._build_sync_response(record)

        assert raised.value.status_code == 400
        assert raised.value.detail == {"error": "No prompt provided in the request"}

    def test_record_without_a_body_is_returned_as_is(self, monkeypatch):
        """Stores that hand back the body alone (get_message contract) still work unchanged."""
        _configure(monkeypatch, mode="rest_sync")

        assert RequestHandler()._build_sync_response({"result": "ok"}) == {"result": "ok"}

    def test_stored_202_surfaces_as_http_202_on_the_poll_route(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_async")
        InMemoryResponseStore().add_message(
            {"session_id": "s1", "request_id": "r-202", "status_code": 202, "body": {"status": "SCHEDULED", "session_id": "s1"}}
        )

        response = _client().get(CHAT, params={"request_id": "r-202"})

        assert response.status_code == 202
        assert response.json() == {"status": "SCHEDULED", "session_id": "s1"}

    def test_stored_error_surfaces_as_http_error_on_the_poll_route(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_async")
        InMemoryResponseStore().add_message({"session_id": "s1", "request_id": "r-500", "status_code": 500, "body": {"error": "agent exploded"}})

        response = _client().get(CHAT, params={"request_id": "r-500"})

        assert response.status_code == 500
        assert response.json()["detail"] == {"error": "agent exploded"}


class TestMultipart:
    def test_multipart_roundtrip_over_the_queue(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode="rest_sync")
        workers()
        response = _client().post(
            RequestHandler.CHAT_MULTIPART_PATH,
            data={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME},
            files=[("images", ("tiny.png", b"\x89PNG-not-really", "image/png"))],
        )
        assert response.status_code == 200
        assert response.json() == {"result": "ok:hello", "session_id": "s1"}

    def test_multipart_rejects_non_image_content_type(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_sync")
        response = _client().post(
            RequestHandler.CHAT_MULTIPART_PATH,
            data={"prompt": "hello", "session_id": "s1"},
            files=[("images", ("evil.exe", b"MZ", "application/octet-stream"))],
        )
        assert response.status_code == 400
        assert "Invalid image type" in response.json()["detail"]["error"]

    def test_multipart_route_absent_on_broker_transports(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_sync")
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "kafka"))
        response = _client().post(RequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "x", "session_id": "s1"})
        assert response.status_code == 404


class TestWebSocketModeGuards:
    """REST chat routes reject the modes whose delivery is the WebSocket route (#495 §9)."""

    def test_async_mode_rejects_rest_chat(self, monkeypatch):
        _configure(monkeypatch, mode="async")
        response = _client().post(CHAT, json={"prompt": "hi", "session_id": "s1"})
        assert response.status_code == 400
        assert "/ws" in response.json()["detail"]["error"]

    def test_realtime_mode_rejects_rest_chat(self, monkeypatch):
        """Realtime replies go to the stateful edge that sent the request; a REST request has none,
        so it must be refused before it is enqueued and opens a model socket."""
        _configure(monkeypatch, mode="realtime")
        response = _client().post(CHAT, json={"prompt": "hi", "session_id": "s1"})
        assert response.status_code == 400
        assert "realtime gateway" in response.json()["detail"]["error"]

        # Nothing was enqueued: the input queue stays empty.
        assert InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.05) == []

    def test_stream_without_a_chunk_streaming_store_rejects_rest_chat(self, monkeypatch):
        """Broker STREAM topologies pair a shared store with WS delivery: the SSE route has
        nothing to drain, so the request must be refused before it is enqueued."""
        _configure(monkeypatch, mode="stream")

        class _NoChunkStore:
            def supports_chunk_streaming(self):
                return False

        handler = RequestHandler()
        handler._response_store = _NoChunkStore()
        app = FastAPI()
        app.include_router(handler.get_router())
        response = TestClient(app).post(CHAT, json={"prompt": "hi", "session_id": "s1"})
        assert response.status_code == 400
        assert "/ws" in response.json()["detail"]["error"]

        # Nothing was enqueued: the input queue stays empty.
        assert InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.05) == []


class TestEnqueueSeam:
    """#524 moved the envelope into RequestProducer; the REST envelope must not have moved with it."""

    def test_the_rest_envelope_is_unchanged(self, monkeypatch):
        _configure(monkeypatch)
        transport = InMemoryTransport()
        handler = RequestHandler()
        monkeypatch.setattr(handler, "get_transport", lambda: transport)

        handler._enqueue_request(BaseRunRequest(prompt="hi", session_id="s1", agent=None), "r1")

        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 0.5)
        # exclude_none, request_id attribute only, session_id as the group, request_id as dedup.
        assert json.loads(message.body) == {"prompt": "hi", "session_id": "s1"}
        assert message.attributes == {"request_id": "r1"}
        assert message.group_id == "s1"
        assert message.dedup_id == "r1"

    def test_get_transport_is_still_the_injection_point(self, monkeypatch):
        _configure(monkeypatch)
        injected = InMemoryTransport()
        handler = RequestHandler()
        monkeypatch.setattr(handler, "get_transport", lambda: injected)

        handler._enqueue_request(BaseRunRequest(prompt="hi", session_id="s1"), "r1")

        assert len(injected.create_consumer(QueueName.INPUT).fetch(1, 0.5)) == 1


class TestResponseWaitSeam:
    """The wait budget and loop REST, A2A and MCP share (#780)."""

    def test_no_response_store_block_waits_sixty_reads_one_second_apart(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.delenv("AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT", raising=False)
        monkeypatch.delenv("AK_EXECUTION__RESPONSE_STORE__DELAY", raising=False)
        AKConfig._reset()

        assert RestHandler()._response_retry_config() == (60, 1.0)

    def test_a_response_store_block_supplies_the_budget(self, monkeypatch):
        _configure(monkeypatch)

        assert RestHandler()._response_retry_config() == (100, 0.05)

    @pytest.mark.asyncio
    async def test_the_wait_uses_the_handlers_own_store_and_budget(self, monkeypatch, sleeps):
        _configure(monkeypatch)
        store = FakeStore()

        assert await _protocol_handler(store, budget=(2, 0.3))._await_response_record("r1") is None
        assert store.reads == [("r1", True), ("r1", True)]
        assert sleeps == [0.3]


class FakeStore:
    """Answers ``get_record`` with None until read ``ready_after`` times, then with ``record``."""

    def __init__(self, record=None, ready_after: int = 0, events: list | None = None):
        self.record = record
        self.ready_after = ready_after
        self.reads: list[tuple[str, bool]] = []
        self.events = events if events is not None else []

    def get_record(self, request_id, get_and_delete=False):
        self.reads.append((request_id, get_and_delete))
        self.events.append("read")
        if self.record is not None and len(self.reads) > self.ready_after:
            return {"request_id": request_id, **self.record}
        return None


class _InjectedHandler(RestHandler):
    """A RestHandler on a given transport, store and budget, through the override seams subclasses use."""

    def __init__(self, store, transport, budget):
        super().__init__()
        self._injected = (store, transport, budget)

    def get_response_store(self):
        return self._injected[0]

    def get_transport(self):
        return self._injected[1]

    def _response_retry_config(self):
        return self._injected[2]


@pytest.fixture
def sleeps(monkeypatch):
    """Record every sleep instead of sleeping."""
    recorded: list[float] = []

    async def _sleep(delay):
        recorded.append(delay)

    monkeypatch.setattr(request_handler.asyncio, "sleep", _sleep)
    return recorded


def _protocol_body(**overrides) -> BaseRunRequest:
    return BaseRunRequest(**{"prompt": "hi", "session_id": "s1", "agent": "triage", **overrides})


def _protocol_handler(store, transport=None, budget=(3, 0.5)) -> RestHandler:
    return _InjectedHandler(store, transport or InMemoryTransport(), budget)


class TestProtocolRequest:
    """``RestHandler.request`` (#780): the "enqueue, then wait for the whole reply" A2A and MCP share with REST."""

    @pytest.fixture(autouse=True)
    def _defaults(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()

    @pytest.mark.asyncio
    async def test_the_message_is_the_rest_envelope_plus_the_protocol(self):
        transport = InMemoryTransport()
        store = FakeStore(record={"status_code": 200, "body": {"result": "ok"}})

        reply = await _protocol_handler(store, transport).request(_protocol_body(), protocol="a2a")

        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 0.5)
        assert json.loads(message.body) == {"prompt": "hi", "session_id": "s1", "agent": "triage"}
        assert message.attributes == {"request_id": reply.request_id, ATTR_PROTOCOL: "a2a"}
        assert message.group_id == "s1"
        assert message.dedup_id == reply.request_id

    @pytest.mark.asyncio
    async def test_each_request_gets_a_fresh_request_id(self):
        store = FakeStore(record={"body": {"result": "ok"}})
        handler = _protocol_handler(store)

        first = await handler.request(_protocol_body(), protocol="mcp")
        second = await handler.request(_protocol_body(), protocol="mcp")

        assert first.request_id != second.request_id
        assert [request_id for request_id, _ in store.reads] == [first.request_id, second.request_id]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides, protocol, message",
        [
            ({"session_id": None}, "a2a", "No session_id is provided in the request"),
            ({"session_id": ""}, "a2a", "No session_id is provided in the request"),
            ({"prompt": ""}, "a2a", "No prompt provided in the request"),
            ({}, "", "protocol is required"),
        ],
    )
    async def test_rejects_before_anything_is_sent(self, overrides, protocol, message):
        transport = InMemoryTransport()
        store = FakeStore(record={"body": {}})

        with pytest.raises(ValueError, match=message):
            await _protocol_handler(store, transport).request(_protocol_body(**overrides), protocol=protocol)

        assert transport.create_consumer(QueueName.INPUT).fetch(1, 0.05) == []
        assert store.reads == []

    @pytest.mark.asyncio
    async def test_the_first_read_comes_before_any_sleep(self, sleeps):
        store = FakeStore(record={"body": {"result": "ok"}})

        await _protocol_handler(store).request(_protocol_body(), protocol="a2a")

        assert len(store.reads) == 1
        assert sleeps == []

    @pytest.mark.asyncio
    async def test_reads_until_the_record_is_there(self, sleeps):
        store = FakeStore(record={"body": {"result": "ok"}}, ready_after=2)

        reply = await _protocol_handler(store, budget=(5, 0.25)).request(_protocol_body(), protocol="a2a")

        assert reply.result == "ok"
        assert len(store.reads) == 3
        assert sleeps == [0.25, 0.25]

    @pytest.mark.asyncio
    async def test_a_spent_budget_is_retry_count_reads_and_one_sleep_fewer(self, monkeypatch):
        events: list = []
        store = FakeStore(events=events)

        async def _sleep(delay):
            events.append(("sleep", delay))

        monkeypatch.setattr(request_handler.asyncio, "sleep", _sleep)

        with pytest.raises(ReplyTimeoutError) as excinfo:
            await _protocol_handler(store, budget=(3, 0.5)).request(_protocol_body(), protocol="mcp")

        assert events == ["read", ("sleep", 0.5), "read", ("sleep", 0.5), "read"]
        assert excinfo.value.request_id == store.reads[0][0]
        assert (excinfo.value.retry_count, excinfo.value.delay) == (3, 0.5)
        assert isinstance(excinfo.value, TimeoutError)

    @pytest.mark.asyncio
    async def test_every_read_deletes_the_record_it_returns(self, sleeps):
        store = FakeStore(record={"body": {}}, ready_after=1)

        await _protocol_handler(store).request(_protocol_body(), protocol="a2a")

        assert all(get_and_delete is True for _, get_and_delete in store.reads)

    @pytest.mark.asyncio
    async def test_an_error_status_is_returned_not_raised(self):
        store = FakeStore(record={"status_code": 500, "body": {"error": "agent exploded"}})

        reply = await _protocol_handler(store).request(_protocol_body(), protocol="a2a")

        assert reply.is_error
        assert reply.error == "agent exploded"

    @pytest.mark.asyncio
    async def test_transport_and_store_errors_reach_the_caller_unchanged(self):
        class BrokenStore:
            def get_record(self, request_id, get_and_delete=False):
                raise ConnectionError("store down")

        with pytest.raises(ConnectionError, match="store down"):
            await _protocol_handler(BrokenStore()).request(_protocol_body(), protocol="a2a")

    @pytest.mark.asyncio
    async def test_execution_mode_never_skips_the_wait(self, monkeypatch):
        """REST_ASYNC answers the REST route with a request id; a protocol caller still gets the reply."""
        _configure(monkeypatch, mode="rest_async")
        store = FakeStore(record={"body": {"result": "ok"}})

        reply = await _protocol_handler(store).request(_protocol_body(), protocol="a2a")

        assert reply.result == "ok"

    @pytest.mark.asyncio
    async def test_the_default_budget_is_read_from_config(self, monkeypatch, sleeps):
        monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT", "2")
        monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__DELAY", "0.125")
        AKConfig._reset()
        store = FakeStore()
        transport = InMemoryTransport()

        class _StoreOnly(RestHandler):
            def get_response_store(self):
                return store

            def get_transport(self):
                return transport

        with pytest.raises(ReplyTimeoutError):
            await _StoreOnly().request(_protocol_body(), protocol="a2a")

        assert len(store.reads) == 2
        assert sleeps == [0.125]

    @pytest.mark.asyncio
    async def test_the_factories_build_the_transport_and_store_once(self, monkeypatch):
        transport = InMemoryTransport()
        store = FakeStore(record={"body": {"result": "ok"}})
        built = []

        def _build(made):
            def _create(*args, **kwargs):
                built.append(made)
                return made

            return _create

        monkeypatch.setattr(QueueTransportFactory, "create", _build(transport))
        monkeypatch.setattr(ResponseStoreFactory, "create", _build(store))
        handler = RestHandler()

        await handler.request(_protocol_body(session_id="s1"), protocol="a2a")
        await handler.request(_protocol_body(session_id="s2"), protocol="a2a")

        # Built once on first use, then reused.
        assert built == [transport, store]
        assert len(transport.create_consumer(QueueName.INPUT).fetch(10, 0.5)) == 2
        assert len(store.reads) == 2


class TestQueuedReply:
    def test_a_missing_status_counts_as_200(self):
        assert QueuedReply.from_record({"request_id": "r1", "body": {}}).status_code == 200
        assert QueuedReply.from_record({"request_id": "r1", "status_code": None, "body": {}}).status_code == 200

    @pytest.mark.parametrize("status_code, is_error", [(200, False), (202, False), (399, False), (400, True), (500, True)])
    def test_is_error_from_400(self, status_code, is_error):
        assert QueuedReply(request_id="r1", status_code=status_code).is_error is is_error

    def test_a_dict_body_exposes_its_fields(self):
        reply = QueuedReply.from_record(
            {"request_id": "r1", "status_code": "200", "body": {"result": {"a": 1}, "media_type": "application/json", "error": "e"}}
        )

        assert reply.request_id == "r1"
        assert reply.status_code == 200
        assert (reply.result, reply.media_type, reply.error) == ({"a": 1}, "application/json", "e")

    @pytest.mark.parametrize("body", [None, "text", ["a"]])
    def test_a_non_dict_body_exposes_nothing(self, body):
        reply = QueuedReply(request_id="r1", body=body)

        assert (reply.result, reply.media_type, reply.error) == (None, None, None)
        assert reply.body == body


class TestStreamErrorFrames:
    """SSE error frames are handler-owned text: a store/driver exception must never reach the client
    (CodeQL py/stack-trace-exposure), only the log."""

    BACKEND_DETAIL = "redis://cache.internal:6379 read timed out after 5.0s (pool=3, db=0)"

    def _frames(self, monkeypatch, exception):
        _configure(monkeypatch, mode="stream")

        def _raise(self, request_id, chunk_timeout=None):
            raise exception
            yield  # pragma: no cover - keeps _raise a generator function

        monkeypatch.setattr(InMemoryResponseStore, "stream", _raise)
        with _client().stream("POST", CHAT, json={"prompt": "hi", "session_id": "s1"}) as response:
            assert response.status_code == 200
            return [json.loads(line[len("data: ") :]) for line in response.iter_lines() if line.startswith("data: ")]

    def test_timeout_frame_omits_the_backend_exception_text(self, monkeypatch):
        frames = self._frames(monkeypatch, TimeoutError(self.BACKEND_DETAIL))

        assert frames == [{"error": "Stream timed out", "done": True, "session_id": "s1"}]
        assert "cache.internal" not in json.dumps(frames)

    def test_failure_frame_omits_the_backend_exception_text(self, monkeypatch):
        frames = self._frames(monkeypatch, RuntimeError(self.BACKEND_DETAIL))

        assert frames == [{"error": "Stream delivery failed", "done": True, "session_id": "s1"}]
        assert "cache.internal" not in json.dumps(frames)
