import base64
import json
import threading

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import AgentDescriptor, AgentReplyText, AgentRequestText, BaseRunRequest, Principal
from agentkernel.core.multimodal.hooks import MultimodalPreHook
from agentkernel.core.multimodal.storage import AttachmentStorageManager
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
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


def _configure(monkeypatch, mode=None, message_type=None):
    """Point AKConfig at real defaults (in_memory transport) with a fast response-wait budget."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    if mode:
        monkeypatch.setenv("AK_EXECUTION__MODE", mode)
    else:
        monkeypatch.delenv("AK_EXECUTION__MODE", raising=False)
    if message_type:
        monkeypatch.setenv("AK_EXECUTION__MESSAGE_TYPE", message_type)
    else:
        monkeypatch.delenv("AK_EXECUTION__MESSAGE_TYPE", raising=False)
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
        assert AGENT_NAME in [entry["id"] for entry in response.json()["agents"]]


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

    def test_resume_without_prompt_is_enqueued(self, monkeypatch, dummy_agent):
        """A human-in-the-loop decision carries no prompt; direct mode accepts it, so the pipeline must too."""
        _configure(monkeypatch, mode="rest_async")
        resume = {"decisions": [{"id": "call_1", "status": "approved"}]}

        accepted = _client().post(CHAT, json={"session_id": "s1", "agent": AGENT_NAME, "resume": resume})

        assert accepted.status_code == 200
        assert accepted.json()["status"] == "ACCEPTED"
        [message] = InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.5)
        assert json.loads(message.body)["resume"]["decisions"][0] == {"id": "call_1", "status": "approved"}

    def test_a_user_id_in_the_body_is_refused_before_the_queue(self, monkeypatch, dummy_agent):
        """Direct-mode parity: ChatService refuses it with a 400 before anything runs, so the edge does too."""
        _configure(monkeypatch, mode="rest_async")

        response = _client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME, "user_id": "u-1"})

        assert response.status_code == 400
        assert "user_id is not a request field" in response.json()["detail"]["error"]
        assert InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.1) == []

    def test_the_authenticated_principal_rides_the_queue(self, monkeypatch, dummy_agent, tmp_path):
        """Mounted through RESTAPI, the route reads the principal the identity dependency established (#603)."""
        from agentkernel.api.http import RESTAPI
        from agentkernel.identity import IdentityProviderFactory
        from agentkernel.secret import SecretManager

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "identity:\n  provider:\n    type: static\n    static:\n      principals:\n        ALICE_TOKEN:\n          subject: alice\n          groups: [ops]\n"
        )
        _configure(monkeypatch, mode="rest_async")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
        monkeypatch.setenv("ALICE_TOKEN", "alice-secret")
        AKConfig._reset()
        SecretManager.reset()
        IdentityProviderFactory.reset()
        try:
            client = TestClient(RESTAPI.build_app([RequestHandler()]))
            accepted = client.post(
                CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME}, headers={"Authorization": "Bearer alice-secret"}
            )
            assert accepted.status_code == 200
            [message] = InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.5)
            principal = json.loads(message.body)["principal"]
            assert (principal["subject"], principal["provider"], principal["groups"]) == ("alice", "static", ["ops"])
            assert client.post(CHAT, json={"prompt": "hello", "session_id": "s1"}, headers={"Authorization": "Bearer mallory"}).status_code == 401
        finally:
            IdentityProviderFactory.reset()
            SecretManager.reset()

    def test_a_principal_sent_by_the_client_never_reaches_the_queue(self, monkeypatch, dummy_agent):
        """The principal is the surface's to assign; until the identity dependency does, the body carries none (#603)."""
        _configure(monkeypatch, mode="rest_async")
        forged = {"subject": "mallory", "provider": "oidc", "namespace": "https://issuer.example"}

        accepted = _client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME, "principal": forged})

        assert accepted.status_code == 200
        [message] = InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.5)
        assert "principal" not in json.loads(message.body)


class _QueuedRestHandler(RestHandler):
    """RestHandler in queue mode: its own enqueue-and-wait route, the one the pipeline handler builds on."""

    def _is_queue_mode(self) -> bool:
        return True


class TestAnAgentKeptOffRest:
    """The queued chat routes say the request entered by the REST API, and the runner serves it only the agents on
    `rest` (#603, design refinement 13). The `kept_off_rest` runtime hosts `internal` (on `a2a` only, registered
    first) and `public`; the runner threads run under it, as the edge does."""

    def test_the_queued_body_carries_the_surface_it_entered_by(self, monkeypatch, kept_off_rest):
        _configure(monkeypatch, mode="rest_async")

        with kept_off_rest:
            _client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "public"})

        [message] = InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.5)
        assert json.loads(message.body)["surface"] == "rest"

    def test_the_base_handlers_own_queue_route_marks_it_too(self, monkeypatch, kept_off_rest):
        _configure(monkeypatch, mode="rest_async")
        app = FastAPI()
        app.include_router(_QueuedRestHandler().get_router())

        with kept_off_rest:
            TestClient(app).post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "public"})

        [message] = InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.5)
        assert json.loads(message.body)["surface"] == "rest"

    def test_the_multipart_route_marks_it_too(self, monkeypatch, kept_off_rest):
        _configure(monkeypatch, mode="rest_async")

        with kept_off_rest:
            _client().post(RequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "hello", "session_id": "s1", "agent": "public"})

        [message] = InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.5)
        assert json.loads(message.body)["surface"] == "rest"

    def test_naming_it_is_answered_with_the_unknown_agents_404(self, monkeypatch, kept_off_rest, workers):
        _configure(monkeypatch, mode="rest_sync")
        with kept_off_rest:
            workers()
            client = _client()
            kept_off = client.post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "internal"})
            unknown = client.post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "ghost"})

        assert kept_off.status_code == unknown.status_code == 404
        assert kept_off.json()["detail"] == {"error": "Agent 'internal' not found", "session_id": "s1"}
        assert unknown.json()["detail"] == {"error": "Agent 'ghost' not found", "session_id": "s1"}

    def test_a_request_naming_no_agent_runs_the_first_agent_on_rest(self, monkeypatch, kept_off_rest, workers):
        _configure(monkeypatch, mode="rest_sync")
        with kept_off_rest:
            workers()
            response = _client().post(CHAT, json={"prompt": "hello", "session_id": "s1"})

        assert response.status_code == 200
        assert response.json() == {"result": "public", "session_id": "s1"}

    def test_the_multipart_route_answers_the_same(self, monkeypatch, kept_off_rest, workers):
        _configure(monkeypatch, mode="rest_sync")
        with kept_off_rest:
            workers()
            client = _client()
            kept_off = client.post(RequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "hello", "session_id": "s1", "agent": "internal"})
            default = client.post(RequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "hello", "session_id": "s1"})

        assert (kept_off.status_code, kept_off.json()["detail"]["error"]) == (404, "Agent 'internal' not found")
        assert default.json() == {"result": "public", "session_id": "s1"}

    def test_the_streamed_default_skips_it(self, monkeypatch, kept_off_rest, workers):
        _configure(monkeypatch, mode="rest_sync", message_type="delta")
        with kept_off_rest:
            workers(stream=True)
            with _client().stream("POST", CHAT, json={"prompt": "hello", "session_id": "s1"}) as response:
                frames = [json.loads(line[len("data: ") :]) for line in response.iter_lines() if line.startswith("data: ")]

        assert "".join(frame.get("delta", "") for frame in frames) == "public"

    def test_a_protocol_request_is_enqueued_as_its_executor_built_it(self, monkeypatch, knows_triage):
        # A2A and MCP reach the queue through ``request``: each executor names its own surface, and this path
        # neither adds ``rest`` nor takes theirs away.
        import asyncio

        _configure(monkeypatch)
        transport = InMemoryTransport()
        store = FakeStore(record={"status_code": 200, "body": {"result": "ok"}})

        # A session each: the queue hands out one message of a session at a time.
        asyncio.run(_protocol_handler(store, transport).request(_protocol_body(session_id="s1", surface="a2a"), protocol="a2a"))
        asyncio.run(_protocol_handler(store, transport).request(_protocol_body(session_id="s2"), protocol="mcp"))

        bodies = {body["session_id"]: body for body in (json.loads(m.body) for m in transport.create_consumer(QueueName.INPUT).fetch(2, 0.5))}
        assert (bodies["s1"]["surface"], "surface" in bodies["s2"]) == ("a2a", False)


class TestInternalFieldsRejected:
    """#884: a client cannot set the fields internal producers use, so a resume decision cannot be dropped."""

    @pytest.mark.parametrize(
        "field, value", [("requests", [{"type": "text", "prompt": "something else"}]), ("scheduled_task_id", "t1"), ("scheduled_time", "x")]
    )
    def test_rejected_with_422_before_anything_is_enqueued(self, monkeypatch, dummy_agent, field, value):
        _configure(monkeypatch, mode="rest_async")
        resume = {"decisions": [{"id": "call_1", "payload": "Store credit"}]}

        response = _client().post(CHAT, json={"session_id": "s1", "agent": AGENT_NAME, "resume": resume, field: value})

        assert response.status_code == 422
        assert InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.1) == []


class TestStreamSSE:
    def test_stream_yields_sse_chunks(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode="rest_sync", message_type="delta")
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
        """The behavior is inherited from RestHandler, not re-implemented on the pipeline handler."""
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

    def test_a_user_id_form_field_is_refused_before_the_queue(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_async")

        response = _client().post(RequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "hello", "session_id": "s1", "user_id": "u-1"})

        assert response.status_code == 400
        assert "user_id is not a request field" in response.json()["detail"]["error"]
        assert InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.1) == []

    def test_multipart_rejects_non_image_content_type(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_sync")
        response = _client().post(
            RequestHandler.CHAT_MULTIPART_PATH,
            data={"prompt": "hello", "session_id": "s1"},
            files=[("images", ("evil.exe", b"MZ", "application/octet-stream"))],
        )
        assert response.status_code == 400
        assert "Invalid image type" in response.json()["detail"]["error"]

    def test_multipart_route_served_on_broker_transports(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, multimodal=False)
        response = client.post(RequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "x", "session_id": "s1", "agent": AGENT_NAME})
        assert response.status_code == 200
        assert len(_queued()) == 1


BASE64_HELLO = "aGVsbG8="


def _broker_client(
    monkeypatch, *, multimodal=True, storage_type="in_memory", shared=None, mode="rest_async", message_type=None, transport=None
) -> TestClient:
    """A handler on a broker transport (#871), with the in-memory transport and store injected so nothing dials out."""
    if multimodal:
        monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
        monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", storage_type)
    _configure(monkeypatch, mode=mode, message_type=message_type)
    monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "kafka"))
    if shared is not None:
        monkeypatch.setattr(AttachmentStorageManager, "store_is_shared", classmethod(lambda cls: shared))
    handler = RequestHandler()
    handler._transport = transport or InMemoryTransport()
    handler._response_store = InMemoryResponseStore()
    app = FastAPI()
    app.include_router(handler.get_router())
    return TestClient(app)


def _queued() -> list:
    return InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.05)


def _with_file(file_data: str, **extra) -> dict:
    return {
        "prompt": "hi",
        "session_id": "s1",
        "agent": AGENT_NAME,
        "files": [{"file_data": file_data, "name": "a.txt", "mime_type": "text/plain"}],
        **extra,
    }


class TestBrokerUploadChecks:
    """#871: on a broker, files that cannot be saved where the runner reads them are refused before the queue."""

    def _assert_refused(self, response, fragment: str) -> None:
        assert response.status_code == 400
        assert fragment in response.json()["detail"]["error"]
        assert response.json()["detail"]["session_id"] == "s1"
        assert _queued() == []

    def test_a_plain_text_data_uri_travels_inline(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, shared=True, transport=_CappedTransport())
        _CappedTransport.sent = []

        assert client.post(CHAT, json=_with_file("data:text/plain,hello%20world")).status_code == 200

        [body] = [json.loads(sent) for sent in _CappedTransport.sent]
        assert body["requests"][1]["file_data"] == "data:text/plain,hello%20world"

    def test_a_store_config_error_is_a_400(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, storage_type="nonsense")
        self._assert_refused(client.post(CHAT, json=_with_file(BASE64_HELLO)), "unknown multimodal storage_type 'nonsense'")

    def test_saved_files_are_capped_at_max_attachments(self, monkeypatch, dummy_agent):
        monkeypatch.setenv("AK_MULTIMODAL__MAX_ATTACHMENTS", "1")
        client = _broker_client(monkeypatch, shared=True)
        seen = []
        real_offload = AttachmentStorageManager.offload.__func__
        monkeypatch.setattr(
            AttachmentStorageManager, "offload", classmethod(lambda cls, *a, **k: seen.append(k["max_attachments"]) or real_offload(cls, *a, **k))
        )

        assert client.post(CHAT, json=_with_file(BASE64_HELLO)).status_code == 200
        assert seen == [1 + 2]  # the cap plus this request's prompt and file

    def test_file_bytes_without_multimodal_are_refused(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, multimodal=False)
        self._assert_refused(client.post(CHAT, json=_with_file(BASE64_HELLO)), "multimodal support is disabled")

    def test_an_image_counts_as_file_bytes(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, multimodal=False)
        body = {"prompt": "hi", "session_id": "s1", "images": [{"image_data": f"data:image/png;base64,{BASE64_HELLO}", "name": "a.png"}]}
        self._assert_refused(client.post(CHAT, json=body), "multimodal support is disabled")

    def test_file_bytes_with_an_unshared_store_are_refused(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, storage_type="in_memory")
        self._assert_refused(client.post(CHAT, json=_with_file(BASE64_HELLO)), "keeps files in the process that saved them")

    def test_a_json_file_over_max_file_size_is_refused(self, monkeypatch, dummy_agent):
        monkeypatch.setenv("AK_API__MAX_FILE_SIZE", "4")
        client = _broker_client(monkeypatch, shared=True)
        self._assert_refused(client.post(CHAT, json=_with_file(BASE64_HELLO)), "exceeds maximum size")

    def test_a_file_at_max_file_size_passes(self, monkeypatch, dummy_agent):
        monkeypatch.setenv("AK_API__MAX_FILE_SIZE", "5")  # "hello" decodes to exactly 5 bytes
        client = _broker_client(monkeypatch, shared=True)
        assert client.post(CHAT, json=_with_file(BASE64_HELLO)).status_code == 200
        assert len(_queued()) == 1

    def test_a_link_needs_no_store(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, multimodal=False)
        assert client.post(CHAT, json=_with_file("https://example.com/a.txt")).status_code == 200
        assert len(_queued()) == 1

    def test_a_text_chat_works_with_an_unshared_store(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, storage_type="in_memory")
        assert client.post(CHAT, json={"prompt": "hi", "session_id": "s1", "agent": AGENT_NAME}).status_code == 200
        assert len(_queued()) == 1

    def test_the_in_memory_transport_is_never_checked(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_async")  # multimodal off: refused on a broker, fine in-process
        response = _client().post(CHAT, json=_with_file("data:text/plain,hello"))
        assert response.status_code == 200
        assert len(_queued()) == 1

    def test_startup_warns_about_an_unshared_store(self, monkeypatch, caplog):
        with caplog.at_level("WARNING", logger="ak.pipeline.request_handler"):
            _broker_client(monkeypatch, storage_type="in_memory")
        assert "File uploads will be refused" in caplog.text
        assert "multimodal.storage_type 'in_memory'" in caplog.text

    def test_startup_survives_an_unknown_store(self, monkeypatch, caplog):
        with caplog.at_level("WARNING", logger="ak.pipeline.request_handler"):
            _broker_client(monkeypatch, storage_type="nonsense")
        assert "unknown multimodal storage_type 'nonsense'" in caplog.text

    def test_startup_survives_a_missing_store_extra(self, monkeypatch, caplog):
        def missing(cls):
            raise ImportError("install agentkernel[redis]")

        monkeypatch.setattr(AttachmentStorageManager, "store_is_shared", classmethod(missing))
        with caplog.at_level("WARNING", logger="ak.pipeline.request_handler"):
            _broker_client(monkeypatch, storage_type="redis")
        assert "File uploads will be refused: install agentkernel[redis]" in caplog.text

    def test_startup_is_quiet_with_a_shared_store(self, monkeypatch, caplog):
        with caplog.at_level("WARNING", logger="ak.pipeline.request_handler"):
            _broker_client(monkeypatch, shared=True)
        assert "File uploads will be refused" not in caplog.text


class _CappedTransport(InMemoryTransport):
    """A broker stand-in: refuses an input message over LIMIT bytes, as SQS, Kafka and NATS do, and keeps what it sent."""

    LIMIT = 64 * 1024
    sent: list[str] = []

    def send(self, queue, message):
        if queue == QueueName.INPUT:
            assert len(message.body.encode()) <= self.LIMIT, f"input message of {len(message.body.encode())} bytes is over the broker limit"
            _CappedTransport.sent.append(message.body)
        return super().send(queue, message)


BIG_FILE = b"x" * (200 * 1024)  # well over the 64 KB cap once base64-encoded


@pytest.fixture
def broker_uploads(monkeypatch):
    """Multimodal on in the runner: the system hooks rebuild from this config, and the description model is stubbed."""
    _CappedTransport.sent = []
    monkeypatch.setattr(Runtime, "_system_pre_hooks", None)
    # The runner and responder build their store through the factory, which refuses in_memory on a broker.
    monkeypatch.setattr(ResponseStoreFactory, "create", staticmethod(lambda *a, **k: InMemoryResponseStore()))
    described: list[str] = []

    async def describe(self, data, mime_type="image/jpeg"):
        described.append(data)
        return "a greeting"

    monkeypatch.setattr(MultimodalPreHook, "_describe_attachment_briefly", describe)
    return described


class TestBrokerUploads:
    """#871: on a broker, uploads are saved at the edge and only their ids ride the queue."""

    def _client(self, monkeypatch, **kwargs) -> TestClient:
        return _broker_client(monkeypatch, shared=True, mode="rest_sync", transport=_CappedTransport(), **kwargs)

    def _assert_only_ids_were_queued(self) -> None:
        [body] = [json.loads(sent) for sent in _CappedTransport.sent]
        assert body.get("files") is None and body.get("images") is None
        assert [req["type"] for req in body["requests"]] == ["text", "attachment_ref"]

    def test_a_json_upload_over_the_broker_limit_round_trips(self, monkeypatch, dummy_agent, workers, broker_uploads):
        client = self._client(monkeypatch)
        workers()

        response = client.post(CHAT, json=_with_file(base64.b64encode(BIG_FILE).decode()))

        assert response.status_code == 200
        assert "a greeting" in response.json()["result"]  # the runner loaded the file by its id and described it
        assert broker_uploads == [base64.b64encode(BIG_FILE).decode()]
        self._assert_only_ids_were_queued()

    def test_a_multipart_upload_over_the_broker_limit_round_trips(self, monkeypatch, dummy_agent, workers, broker_uploads):
        client = self._client(monkeypatch)
        workers()

        response = client.post(
            RequestHandler.CHAT_MULTIPART_PATH,
            data={"prompt": "hi", "session_id": "s1", "agent": AGENT_NAME},
            files=[("files", ("big.bin", BIG_FILE, "application/octet-stream"))],
        )

        assert response.status_code == 200
        assert "a greeting" in response.json()["result"]
        self._assert_only_ids_were_queued()

    def test_a_streamed_upload_over_the_broker_limit_round_trips(self, monkeypatch, dummy_agent, workers, broker_uploads):
        client = self._client(monkeypatch, message_type="delta")
        # The in-memory response store is process-local; here edge and runner share the process.
        monkeypatch.setattr(RequestHandler, "_store_can_serve_sse", lambda self: True)
        workers(stream=True)

        with client.stream("POST", CHAT, json=_with_file(base64.b64encode(BIG_FILE).decode())) as response:
            assert response.status_code == 200
            frames = [json.loads(line[len("data: ") :]) for line in response.iter_lines() if line.startswith("data: ")]

        assert frames[-1]["done"] is True
        assert broker_uploads == [base64.b64encode(BIG_FILE).decode()]
        self._assert_only_ids_were_queued()

    def test_a_streamed_multipart_upload_over_the_broker_limit_round_trips(self, monkeypatch, dummy_agent, workers, broker_uploads):
        client = self._client(monkeypatch, message_type="delta")
        monkeypatch.setattr(RequestHandler, "_store_can_serve_sse", lambda self: True)
        workers(stream=True)

        with client.stream(
            "POST",
            RequestHandler.CHAT_MULTIPART_PATH,
            data={"prompt": "hi", "session_id": "s1", "agent": AGENT_NAME},
            files=[("files", ("big.bin", BIG_FILE, "application/octet-stream"))],
        ) as response:
            assert response.status_code == 200
            frames = [json.loads(line[len("data: ") :]) for line in response.iter_lines() if line.startswith("data: ")]

        assert frames[-1]["done"] is True
        assert broker_uploads == [base64.b64encode(BIG_FILE).decode()]
        self._assert_only_ids_were_queued()

    def test_a_link_travels_untouched(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, shared=True, transport=_CappedTransport())
        _CappedTransport.sent = []

        assert client.post(CHAT, json=_with_file("https://example.com/a.txt")).status_code == 200

        [body] = [json.loads(sent) for sent in _CappedTransport.sent]
        assert body["requests"][1]["file_data"] == "https://example.com/a.txt"

    def test_a_scheduled_request_saves_and_queues_no_file(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, shared=True, transport=_CappedTransport())
        _CappedTransport.sent = []
        monkeypatch.setattr(
            AttachmentStorageManager, "offload", classmethod(lambda cls, *a, **k: pytest.fail("a deferred request must not save files"))
        )
        big = base64.b64encode(BIG_FILE).decode()

        response = client.post(CHAT, json=_with_file(big, schedule={"at": "2099-01-01T00:00:00"}))

        assert response.status_code == 200
        [body] = [json.loads(sent) for sent in _CappedTransport.sent]
        assert not body.get("files") and body["prompt"] == "hi"
        assert body["schedule"]["at"].startswith("2099-01-01T00:00:00")

    def test_a_save_the_store_refuses_is_a_400(self, monkeypatch, dummy_agent):
        client = _broker_client(monkeypatch, shared=True)

        def refuse(cls, *args, **kwargs):
            raise ValueError("Attachment a.txt is 500 KB stored, over DynamoDB's 400 KB item limit.")

        monkeypatch.setattr(AttachmentStorageManager, "offload", classmethod(refuse))

        response = client.post(CHAT, json=_with_file(BASE64_HELLO))

        assert response.status_code == 400
        assert "400 KB item limit" in response.json()["detail"]["error"]
        assert _queued() == []


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
        assert "realtime edge" in response.json()["detail"]["error"]

        # Nothing was enqueued: the input queue stays empty.
        assert InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.05) == []

    def test_async_delta_mode_rejects_rest_chat(self, monkeypatch):
        _configure(monkeypatch, mode="async", message_type="delta")
        response = _client().post(CHAT, json={"prompt": "hi", "session_id": "s1"})
        assert response.status_code == 400
        assert "/ws" in response.json()["detail"]["error"]

        # Nothing was enqueued: the input queue stays empty.
        assert InMemoryTransport().create_consumer(QueueName.INPUT).fetch(1, 0.05) == []

    def test_sse_with_a_process_local_store_rejects_rest_chat_on_a_broker(self, monkeypatch):
        """The other half of `_store_can_serve_sse`: the in-memory store *can* stream chunks, but
        holds them in class-level state, so on a broker the edge and the Response Handler hold
        separate copies and the request would hang out its whole budget before timing out."""
        _configure(monkeypatch, mode="rest_sync", message_type="delta")
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))

        handler = RequestHandler()
        handler._response_store = InMemoryResponseStore()
        app = FastAPI()
        app.include_router(handler.get_router())
        response = TestClient(app).post(CHAT, json={"prompt": "hi", "session_id": "s1"})
        assert response.status_code == 400
        assert "shared with the response handler" in response.json()["detail"]["error"]

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


@pytest.fixture
def knows_triage(descriptor_only_registry):
    """A runtime of the test's own whose registry knows `triage`, the agent the protocol bodies name.

    `request` asks whether the agent is available before it enqueues (#603). Under the shared global runtime the
    answer would depend on what an earlier test module left registered there.
    """
    with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([AgentDescriptor(id="triage", name="triage")])):
        yield


class TestProtocolRequest:
    """``RestHandler.request`` (#780): the "enqueue, then wait for the whole reply" A2A and MCP share with REST."""

    @pytest.fixture(autouse=True)
    def _defaults(self, monkeypatch, knows_triage):
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
        _configure(monkeypatch, mode="rest_sync", message_type="delta")

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


# -- the precheck before the queue (#603, plan iteration 19) ---------------------------------------


ALICE = Principal(subject="alice", provider="static", namespace="static")
BOB = Principal(subject="bob", provider="static", namespace="static")

# What the edge of a split deployment knows: descriptors of agents another process hosts. `assistant` is private,
# `status` is public, `internal` is kept off the REST surface.
EDGE_AGENTS = [
    AgentDescriptor(id="assistant", name="assistant"),
    AgentDescriptor(id="status", name="status", visibility="public"),
    AgentDescriptor(id="internal", name="internal", surfaces=["a2a"]),
]
GRANTS = [{"subjects": ["user:alice"], "agents": ["assistant", "internal"], "level": "read"}]


def _edge_client(handler=None, principal: Principal | None = None) -> TestClient:
    """The queue routes of an edge process, with the principal an identity dependency would have set."""

    async def _identity(request: Request):
        request.state.principal = principal or Principal.anonymous()

    app = FastAPI()
    app.include_router((handler or RequestHandler()).get_router(), dependencies=[Depends(_identity)])
    return TestClient(app)


def _queued_bodies() -> list[dict]:
    return [json.loads(message.body) for message in InMemoryTransport().create_consumer(QueueName.INPUT).fetch(10, 0.1)]


@pytest.fixture
def edge(descriptor_only_registry):
    """The current runtime of an edge process: a registry that knows `EDGE_AGENTS` and hosts none of them.

    `edge.reads` counts the registry reads a request cost, and `edge.threads` names the threads that made them.
    """

    class _CountingRegistry(descriptor_only_registry):
        def __init__(self, descriptors):
            super().__init__(descriptors)
            self.reads: list[str] = []
            self.threads: set[str] = set()

        def _read(self, what: str) -> None:
            self.reads.append(what)
            self.threads.add(threading.current_thread().name)

        def descriptor(self, id):
            self._read(f"descriptor:{id}")
            return super().descriptor(id)

        def descriptors(self):
            self._read("descriptors")
            return super().descriptors()

        def is_empty(self):
            self._read("is_empty")
            return super().is_empty()

    registry = _CountingRegistry(EDGE_AGENTS)
    with Runtime(InMemorySessionStore(), registry=registry):
        yield registry


class TestThePrecheckBeforeTheQueue:
    """A request for an agent its caller cannot have is answered by the process that accepts it, with the status
    and body the runner would have answered, and nothing is enqueued (#603, spec 8.3). The edge reads the agent
    registry, so it decides for agents another process hosts; the runner asks again when the request runs."""

    def test_a_request_for_an_agent_the_registry_knows_is_enqueued(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_async")

        response = _edge_client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "assistant"})

        assert response.status_code == 200
        assert [body["agent"] for body in _queued_bodies()] == ["assistant"]

    def test_an_unknown_agent_is_the_404_the_runner_answers_and_nothing_is_enqueued(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_sync")

        response = _edge_client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "ghost"})

        assert response.status_code == 404
        assert response.json() == {"detail": {"error": "Agent 'ghost' not found", "session_id": "s1"}}
        assert _queued_bodies() == []

    def test_the_edges_own_view_of_surfaces_holds_for_a_queued_request(self, monkeypatch, edge):
        # Iteration 17b left this to the runner's descriptor. An agent the edge's registry keeps off `rest` is refused here.
        _configure(monkeypatch, mode="rest_async")

        response = _edge_client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "internal"})

        assert (response.status_code, response.json()["detail"]["error"]) == (404, "Agent 'internal' not found")
        assert _queued_bodies() == []

    def test_with_authorization_a_hidden_agent_and_an_unknown_one_are_one_answer(self, monkeypatch, edge, authorization):
        _configure(monkeypatch, mode="rest_async")
        authorization(grants=GRANTS)
        client = _edge_client(principal=BOB)

        hidden = client.post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "assistant"})
        unknown = client.post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "ghost"})

        assert hidden.status_code == unknown.status_code == 404
        assert hidden.json() == {"detail": {"error": "Agent 'assistant' not found", "session_id": "s1"}}
        assert unknown.json() == {"detail": {"error": "Agent 'ghost' not found", "session_id": "s1"}}
        assert _queued_bodies() == []

    def test_with_authorization_an_agent_the_caller_sees_and_may_not_use_is_a_403(self, monkeypatch, edge, authorization):
        _configure(monkeypatch, mode="rest_async")
        authorization(grants=GRANTS)

        response = _edge_client(principal=BOB).post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "status"})

        assert response.status_code == 403
        assert response.json() == {"detail": {"error": "Principal 'bob' holds no level on agent 'status'", "session_id": "s1"}}
        assert _queued_bodies() == []

    def test_with_authorization_a_caller_with_a_level_is_enqueued_as_itself(self, monkeypatch, edge, authorization):
        _configure(monkeypatch, mode="rest_async")
        authorization(grants=GRANTS)

        response = _edge_client(principal=ALICE).post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "assistant"})

        assert response.status_code == 200
        [body] = _queued_bodies()
        assert (body["agent"], body["principal"]["subject"]) == ("assistant", "alice")

    def test_a_grant_does_not_put_an_agent_on_a_surface_it_is_kept_off(self, monkeypatch, edge, authorization):
        _configure(monkeypatch, mode="rest_async")
        authorization(grants=GRANTS)  # alice holds a level on `internal`, which is on `a2a` only

        response = _edge_client(principal=ALICE).post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "internal"})

        assert response.status_code == 404

    def test_a_request_nobody_authenticated_is_decided_as_the_anonymous_principal(self, monkeypatch, edge, authorization):
        _configure(monkeypatch, mode="rest_async")
        authorization(grants=GRANTS)
        app = FastAPI()
        app.include_router(RequestHandler().get_router())  # mounted with no identity dependency at all

        response = TestClient(app).post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "assistant"})

        assert response.status_code == 404
        assert _queued_bodies() == []

    def test_it_is_refused_on_the_sse_path_before_the_stream_opens(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_sync", message_type="delta")

        response = _edge_client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "ghost"})

        assert response.status_code == 404
        assert response.json() == {"detail": {"error": "Agent 'ghost' not found", "session_id": "s1"}}
        assert not response.headers["content-type"].startswith("text/event-stream")
        assert _queued_bodies() == []

    def test_the_multipart_route_refuses_it_too(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_async")

        response = _edge_client().post(RequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "hello", "session_id": "s1", "agent": "ghost"})

        assert (response.status_code, response.json()["detail"]["error"]) == (404, "Agent 'ghost' not found")
        assert _queued_bodies() == []

    def test_the_base_handlers_own_queue_route_refuses_it_too(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_async")

        response = _edge_client(_QueuedRestHandler()).post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "ghost"})

        assert response.status_code == 404
        assert response.json() == {"detail": {"error": "Agent 'ghost' not found", "session_id": "s1"}}
        assert _queued_bodies() == []

    def test_no_file_is_saved_for_a_request_that_is_refused(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_async")
        saved = []

        async def _offload(self, body):
            saved.append(body.agent)

        monkeypatch.setattr(RequestHandler, "_offload_attachments", _offload)
        client = _edge_client()

        client.post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "ghost"})
        client.post(CHAT, json={"prompt": "hello", "session_id": "s2", "agent": "assistant"})

        assert saved == ["assistant"]

    def test_the_registry_is_read_once_for_a_request_and_off_the_event_loop(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_async")
        loop_thread = []

        async def _identity(request: Request):
            loop_thread.append(threading.current_thread().name)
            request.state.principal = Principal.anonymous()

        app = FastAPI()
        app.include_router(RequestHandler().get_router(), dependencies=[Depends(_identity)])

        TestClient(app).post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "assistant"})

        # A store read blocks: made on the loop it would hold every other request of the process.
        assert edge.reads == ["descriptor:assistant"]
        assert edge.threads.isdisjoint(loop_thread)

    def test_a_request_naming_no_agent_is_left_to_the_process_that_picks_the_default(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_async")

        response = _edge_client().post(CHAT, json={"prompt": "hello", "session_id": "s1"})

        assert response.status_code == 200
        assert edge.reads == []  # nothing to look up, and no listing to second-guess the runner's default
        assert len(_queued_bodies()) == 1

    def test_an_edge_that_knows_no_agent_leaves_the_decision_to_the_runner(self, monkeypatch, descriptor_only_registry):
        """A split deployment whose accepting process neither loads the agent modules nor shares a registry has
        nothing to judge a name by. It enqueued every request before the precheck existed, and still does."""
        _configure(monkeypatch, mode="rest_async")

        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([])):
            response = _edge_client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "assistant"})

        assert response.status_code == 200
        assert [body["agent"] for body in _queued_bodies()] == ["assistant"]

    def test_a_deferred_request_for_an_agent_its_caller_cannot_have_is_refused_before_the_queue(self, monkeypatch, edge):
        _configure(monkeypatch, mode="rest_async")
        schedule = {"at": "2999-01-01T00:00:00Z"}

        response = _edge_client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "ghost", "schedule": schedule})

        assert (response.status_code, response.json()["detail"]["error"]) == (404, "Agent 'ghost' not found")
        assert _queued_bodies() == []

    def test_what_the_runner_would_run_is_what_the_edge_let_through(self, monkeypatch, kept_off_rest, workers):
        # Single process, nothing mocked: the same request answered by the edge and, for a served agent, by the runner.
        _configure(monkeypatch, mode="rest_sync")
        with kept_off_rest:
            workers()
            client = _client()
            refused = client.post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": "internal"})
            served = client.post(CHAT, json={"prompt": "hello", "session_id": "s2", "agent": "public"})

        assert (refused.status_code, refused.json()["detail"]) == (404, {"error": "Agent 'internal' not found", "session_id": "s1"})
        assert served.json() == {"result": "public", "session_id": "s2"}


class TestThePrecheckOnAProtocolRequest:
    """`RestHandler.request`, the path A2A and MCP enqueue by, asks the same question with the principal and the
    surface its executor put on the body. A refusal comes back as the reply the runner would have stored: this
    path raises no HTTP error, and its callers already read `is_error`."""

    @pytest.fixture(autouse=True)
    def _defaults(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()

    @pytest.mark.asyncio
    async def test_an_unknown_agent_is_answered_without_the_queue_or_the_store(self, edge):
        transport = InMemoryTransport()
        store = FakeStore(record={"status_code": 200, "body": {"result": "ok"}})

        reply = await _protocol_handler(store, transport).request(_protocol_body(agent="ghost"), protocol="a2a")

        assert (reply.status_code, reply.is_error) == (404, True)
        assert reply.body == {"error": "Agent 'ghost' not found", "session_id": "s1"}
        assert reply.error == "Agent 'ghost' not found"
        assert reply.request_id  # a refused request is still one request, with an id to log by
        assert transport.create_consumer(QueueName.INPUT).fetch(1, 0.1) == []
        assert store.reads == []

    @pytest.mark.asyncio
    async def test_the_surface_the_executor_named_is_the_one_applied(self, edge):
        store = FakeStore(record={"status_code": 200, "body": {"result": "ok"}})

        on_a2a = await _protocol_handler(store).request(_protocol_body(agent="internal", surface="a2a"), protocol="a2a")
        on_mcp = await _protocol_handler(store).request(_protocol_body(agent="internal", session_id="s2", surface="mcp"), protocol="mcp")

        assert (on_a2a.status_code, on_mcp.status_code) == (200, 404)

    @pytest.mark.asyncio
    async def test_with_authorization_the_principal_on_the_body_is_who_is_asked_about(self, edge, authorization):
        authorization(grants=GRANTS)
        store = FakeStore(record={"status_code": 200, "body": {"result": "ok"}})
        handler = _protocol_handler(store)

        granted = await handler.request(_protocol_body(agent="assistant", principal=ALICE), protocol="mcp")
        hidden = await handler.request(_protocol_body(agent="assistant", session_id="s2", principal=BOB), protocol="mcp")
        forbidden = await handler.request(_protocol_body(agent="status", session_id="s3", principal=BOB), protocol="mcp")
        nobody = await handler.request(_protocol_body(agent="assistant", session_id="s4"), protocol="mcp")

        assert (granted.status_code, hidden.status_code, forbidden.status_code, nobody.status_code) == (200, 404, 403, 404)
        assert forbidden.body == {"error": "Principal 'bob' holds no level on agent 'status'", "session_id": "s3"}

    @pytest.mark.asyncio
    async def test_an_edge_that_knows_no_agent_enqueues_as_before(self, descriptor_only_registry):
        transport = InMemoryTransport()
        store = FakeStore(record={"status_code": 200, "body": {"result": "ok"}})

        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([])):
            reply = await _protocol_handler(store, transport).request(_protocol_body(), protocol="a2a")

        assert reply.status_code == 200
        assert len(transport.create_consumer(QueueName.INPUT).fetch(1, 0.1)) == 1
