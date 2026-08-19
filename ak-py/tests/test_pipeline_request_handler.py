import json
import threading

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.consumer import ConsumerLoop
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.request_handler import RequestHandler, RestHandler
from agentkernel.pipeline.response_handler import ResponseHandler
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
        for token in ["he", "llo"]:
            yield token


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
        # delta frames carry done=False, the terminal frame done=True.
        assert frames[0] == {"delta": "he", "done": False, "session_id": "s1"}
        assert frames[1] == {"delta": "llo", "done": False, "session_id": "s1"}
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

        assert isinstance(response, JSONResponse)
        assert response.status_code == 202
        assert json.loads(response.body) == {"status": "SCHEDULED", "session_id": "s1"}

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
