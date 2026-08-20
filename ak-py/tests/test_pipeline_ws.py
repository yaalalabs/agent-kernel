"""Gateway-tier WebSocket delivery (#495 §9): the local socket registry, the shared connection
store, the /ws route, the push endpoint, store-lookup delivery, the gateway entry point, and the
end-to-end gates: single-process ASYNC/STREAM over in_memory plus cross-"pod" delivery between
two gateway apps."""

import asyncio
import json
import threading
import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agentkernel.auth.handler import AuthValidator, ValidationResult
from agentkernel.core.model import ExecutionMode
from agentkernel.core.session.in_memory import InMemoryWSConnectionStore
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.envelope import ATTR_REQUEST_ID, ATTR_USER_ID, QueueName
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.pipeline.ws import push as ws_push
from agentkernel.pipeline.ws.endpoint import PushEndpointHandler
from agentkernel.pipeline.ws.gateway import WebSocketGateway
from agentkernel.pipeline.ws.handler import PipelineWebSocketHandler
from agentkernel.pipeline.ws.push import LOCAL_ENDPOINT, PUSH_PATH, PUSH_TOKEN_HEADER, PodPushWebSocketHandler, pod_endpoint_url
from agentkernel.pipeline.ws.registry import LocalConnectionRegistry

WS_PATH = PipelineWebSocketHandler.WS_PATH


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    InMemoryWSConnectionStore.reset()
    LocalConnectionRegistry.reset()
    PipelineWebSocketHandler._custom_routes.clear()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    InMemoryWSConnectionStore.reset()
    LocalConnectionRegistry.reset()
    PipelineWebSocketHandler._custom_routes.clear()


def _use_config(monkeypatch, mode=None, chat_route=None, push_auth_token=None, push_port=None, api_port=8000):
    class _WebSocketAPI:
        pass

    _WebSocketAPI.chat_route = chat_route
    _WebSocketAPI.push_auth_token = push_auth_token
    _WebSocketAPI.push_port = push_port

    class _Input:
        url = None
        max_receive_count = 3

    class _Output:
        max_receive_count = 3

    class _Queues:
        type = None
        input = _Input
        output = _Output

    class _Api:
        host = "127.0.0.1"

    _Api.port = api_port

    class _Cfg:
        websocket_api = _WebSocketAPI
        api = _Api

        class execution:
            queues = _Queues

    _Cfg.execution.mode = mode
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
    return _Cfg


def _store() -> InMemoryWSConnectionStore:
    # Process-wide class-level state; the autouse fixture resets it between tests.
    return InMemoryWSConnectionStore()


class _Validator(AuthValidator):
    def validate(self, token, context=None):
        if token == "good":
            return ValidationResult(is_valid=True, claims={"userId": "user-1"})
        if token == "no-user":
            return ValidationResult(is_valid=True, claims={})
        return ValidationResult(is_valid=False, error_msg="bad token")


class _FakeSocket:
    def __init__(self, fail=False):
        self.frames = []
        self._fail = fail

    async def send_json(self, message):
        if self._fail:
            raise RuntimeError("connection gone")
        self.frames.append(message)


@pytest.fixture
def bg_loop():
    """A live event loop on a background thread, standing in for the uvicorn loop."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


class TestLocalConnectionRegistry:
    def test_round_trip_and_lookups(self):
        registry = LocalConnectionRegistry()
        registry.add_connection("u1", "c1")
        registry.add_connection("u1", "c2")
        registry.add_connection("u2", "c3")

        assert sorted(registry.get_connections("u1")) == ["c1", "c2"]
        assert registry.get_user_id("c3") == "u2"
        assert registry.get_user_id("nope") is None

        registry.delete_connection("u1", "c1")
        assert registry.get_connections("u1") == ["c2"]
        registry.delete_by_connection_id("c2")
        assert registry.get_connections("u1") == []
        assert registry.get_user_id("c2") is None

    def test_deliver_to_connection_writes_the_socket(self, bg_loop):
        registry = LocalConnectionRegistry()
        socket_ = _FakeSocket()
        registry.add_connection("u1", "c1", websocket=socket_, loop=bg_loop)

        assert registry.deliver_to_connection("c1", {"result": "ok"}) is True
        assert socket_.frames == [{"result": "ok"}]

    def test_failing_connection_is_dropped(self, bg_loop):
        registry = LocalConnectionRegistry()
        registry.add_connection("u1", "dead", websocket=_FakeSocket(fail=True), loop=bg_loop)

        assert registry.deliver_to_connection("dead", {"x": 1}) is False
        assert registry.get_connections("u1") == []

    def test_unknown_connection_delivers_false(self):
        assert LocalConnectionRegistry().deliver_to_connection("ghost", {}) is False

    def test_instance_is_process_wide(self):
        assert LocalConnectionRegistry.instance() is LocalConnectionRegistry.instance()


class TestPodEndpointUrl:
    def test_in_memory_transport_short_circuits_to_local(self, monkeypatch):
        _use_config(monkeypatch)
        assert pod_endpoint_url() == LOCAL_ENDPOINT

    def test_pod_ip_env_and_api_port(self, monkeypatch):
        _use_config(monkeypatch, api_port=9000)
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "kafka"))
        monkeypatch.setenv("AK_POD_IP", "10.1.2.3")
        assert pod_endpoint_url() == "http://10.1.2.3:9000"

    def test_push_port_overrides_api_port(self, monkeypatch):
        _use_config(monkeypatch, api_port=9000, push_port=9100)
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "kafka"))
        monkeypatch.setenv("AK_POD_IP", "10.1.2.3")
        assert pod_endpoint_url() == "http://10.1.2.3:9100"

    def test_falls_back_to_loopback_when_the_host_cannot_be_resolved(self, monkeypatch):
        _use_config(monkeypatch)
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "kafka"))
        monkeypatch.delenv("AK_POD_IP", raising=False)
        monkeypatch.setattr(ws_push.socket, "gethostbyname", lambda name: (_ for _ in ()).throw(OSError("no dns")))
        assert pod_endpoint_url() == "http://127.0.0.1:8000"


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakePushClient:
    def __init__(self, status_code=200):
        self.posts = []
        self._status_code = status_code

    def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(self._status_code)


class TestPodPushWebSocketHandler:
    def test_local_endpoint_delivers_through_the_registry(self, monkeypatch, bg_loop):
        _use_config(monkeypatch)
        store, registry = _store(), LocalConnectionRegistry()
        socket_ = _FakeSocket()
        registry.add_connection("u1", "c1", websocket=socket_, loop=bg_loop)
        store.add_connection("u1", "c1", endpoint=LOCAL_ENDPOINT)

        handler = PodPushWebSocketHandler(connection_store=store, registry=registry)
        handler.broadcast(message={"result": "ok"}, user_id="u1", message_type=handler.MessageType.CHAT_RESPONSE)
        assert socket_.frames == [{"result": "ok", "type": "CHAT_RESPONSE"}]

    def test_user_without_connections_raises_for_retry(self, monkeypatch):
        _use_config(monkeypatch)
        handler = PodPushWebSocketHandler(connection_store=_store(), registry=LocalConnectionRegistry())
        with pytest.raises(LookupError, match="no WebSocket connections registered"):
            handler.broadcast(message={}, user_id="u1")

    def test_broadcast_requires_an_addressee(self, monkeypatch):
        _use_config(monkeypatch)
        with pytest.raises(ValueError, match="user_id or connection_ids"):
            PodPushWebSocketHandler(connection_store=_store(), registry=LocalConnectionRegistry()).broadcast(message={})

    def test_remote_endpoint_posts_per_connection_with_the_token(self, monkeypatch):
        _use_config(monkeypatch, push_auth_token="s3cret")
        client = _FakePushClient()
        monkeypatch.setattr(ws_push, "_pooled_client", lambda: client)
        store = _store()
        store.add_connection("u1", "c1", endpoint="http://10.0.0.7:8000")

        handler = PodPushWebSocketHandler(connection_store=store, registry=LocalConnectionRegistry())
        handler.broadcast(message={"delta": "x"}, user_id="u1", message_type=handler.MessageType.STREAM_CHUNK)

        [post] = client.posts
        assert post["url"] == f"http://10.0.0.7:8000{PUSH_PATH}"
        assert post["headers"] == {PUSH_TOKEN_HEADER: "s3cret"}
        assert post["json"] == {"connection_id": "c1", "message": {"delta": "x", "type": "STREAM_CHUNK"}}

    def test_remote_endpoint_without_a_token_raises(self, monkeypatch):
        _use_config(monkeypatch)
        store = _store()
        store.add_connection("u1", "c1", endpoint="http://10.0.0.7:8000")
        handler = PodPushWebSocketHandler(connection_store=store, registry=LocalConnectionRegistry())
        with pytest.raises(AKConfigError, match="push_auth_token"):
            handler.broadcast(message={}, user_id="u1")

    def test_gone_connection_is_cleaned_up_and_the_rest_still_deliver(self, monkeypatch, bg_loop):
        """One stale mapping (its pod answers 404) must not fail the whole broadcast: it is
        deleted, the live connection gets the frame (GoneException parity)."""
        _use_config(monkeypatch, push_auth_token="s3cret")
        monkeypatch.setattr(ws_push, "_pooled_client", lambda: _FakePushClient(status_code=404))
        store, registry = _store(), LocalConnectionRegistry()
        live = _FakeSocket()
        registry.add_connection("u1", "c-live", websocket=live, loop=bg_loop)
        store.add_connection("u1", "c-live", endpoint=LOCAL_ENDPOINT)
        store.add_connection("u1", "c-stale", endpoint="http://10.0.0.9:8000")

        handler = PodPushWebSocketHandler(connection_store=store, registry=registry)
        handler.broadcast(message={"result": "ok"}, user_id="u1")

        assert live.frames == [{"result": "ok"}]
        assert store.get_endpoints("u1") == {"c-live": LOCAL_ENDPOINT}, "the stale mapping was deleted"

    def test_all_connections_gone_raises_for_retry(self, monkeypatch):
        _use_config(monkeypatch, push_auth_token="s3cret")
        monkeypatch.setattr(ws_push, "_pooled_client", lambda: _FakePushClient(status_code=404))
        store = _store()
        store.add_connection("u1", "c1", endpoint="http://10.0.0.9:8000")
        handler = PodPushWebSocketHandler(connection_store=store, registry=LocalConnectionRegistry())
        with pytest.raises(LookupError, match="no reachable"):
            handler.broadcast(message={}, user_id="u1")
        assert store.get_endpoints("u1") == {}

    def test_transient_push_failure_keeps_the_mapping_and_raises(self, monkeypatch):
        """A 5xx/unreachable pod is not proof the socket is gone: keep the mapping and let the
        message-level retry try again."""
        _use_config(monkeypatch, push_auth_token="s3cret")
        monkeypatch.setattr(ws_push, "_pooled_client", lambda: _FakePushClient(status_code=500))
        store = _store()
        store.add_connection("u1", "c1", endpoint="http://10.0.0.9:8000")
        handler = PodPushWebSocketHandler(connection_store=store, registry=LocalConnectionRegistry())
        with pytest.raises(LookupError, match="no reachable"):
            handler.broadcast(message={}, user_id="u1")
        assert store.get_endpoints("u1") == {"c1": "http://10.0.0.9:8000"}


class TestPushEndpoint:
    def _client(self, registry):
        app = FastAPI()
        app.include_router(PushEndpointHandler(registry=registry).get_router())
        return TestClient(app)

    def test_fails_closed_when_no_token_is_configured(self, monkeypatch):
        _use_config(monkeypatch)
        response = self._client(LocalConnectionRegistry()).post(
            PUSH_PATH, json={"connection_id": "c1", "message": {}}, headers={PUSH_TOKEN_HEADER: "anything"}
        )
        assert response.status_code == 403

    def test_rejects_a_wrong_or_missing_token(self, monkeypatch):
        _use_config(monkeypatch, push_auth_token="s3cret")
        client = self._client(LocalConnectionRegistry())
        assert client.post(PUSH_PATH, json={"connection_id": "c1", "message": {}}, headers={PUSH_TOKEN_HEADER: "wrong"}).status_code == 401
        assert client.post(PUSH_PATH, json={"connection_id": "c1", "message": {}}).status_code == 401

    def test_404_when_the_connection_is_not_held_here(self, monkeypatch):
        _use_config(monkeypatch, push_auth_token="s3cret")
        response = self._client(LocalConnectionRegistry()).post(
            PUSH_PATH, json={"connection_id": "ghost", "message": {}}, headers={PUSH_TOKEN_HEADER: "s3cret"}
        )
        assert response.status_code == 404

    def test_delivers_to_the_named_connection(self, monkeypatch, bg_loop):
        _use_config(monkeypatch, push_auth_token="s3cret")
        registry = LocalConnectionRegistry()
        socket_ = _FakeSocket()
        registry.add_connection("u1", "c1", websocket=socket_, loop=bg_loop)

        response = self._client(registry).post(
            PUSH_PATH,
            json={"connection_id": "c1", "message": {"result": "ok", "type": "CHAT_RESPONSE"}},
            headers={PUSH_TOKEN_HEADER: "s3cret"},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "SUCCESS"}
        assert socket_.frames == [{"result": "ok", "type": "CHAT_RESPONSE"}]


def _ws_app(monkeypatch, mode=None, chat_route=None):
    _use_config(monkeypatch, mode=mode, chat_route=chat_route)
    registry = LocalConnectionRegistry()
    transport = InMemoryTransport()
    store = _store()
    handler = PipelineWebSocketHandler(auth_validator=_Validator(), registry=registry, transport=transport, connection_store=store)
    app = FastAPI()
    app.include_router(handler.get_router())
    return app, registry, transport, store


class TestWebSocketAuthentication:
    @pytest.mark.parametrize(
        "query,reason",
        [
            ("", "Authentication token is required"),
            ("?token=bad", "bad token"),
            ("?token=no-user", "'userId' claim is required in token"),
        ],
    )
    def test_handshake_rejections_close_with_policy_violation(self, monkeypatch, query, reason):
        app, _, _, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}{query}") as websocket:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()
        assert exc_info.value.code == 1008
        assert exc_info.value.reason == reason

    def test_validator_is_mandatory(self):
        with pytest.raises(ValueError, match="auth_validator is required"):
            PipelineWebSocketHandler(auth_validator=None)

    def test_connection_registers_and_deregisters_in_registry_and_store(self, monkeypatch):
        app, registry, _, store = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "nope"})
            websocket.receive_json()  # ensure the server processed the handshake fully
            [connection_id] = registry.get_connections("user-1")
            assert store.get_endpoints("user-1") == {connection_id: LOCAL_ENDPOINT}
        deadline = time.monotonic() + 2
        while (registry.get_connections("user-1") or store.get_connections("user-1")) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert registry.get_connections("user-1") == []
        assert store.get_connections("user-1") == [], "the shared mapping is cleaned on disconnect"


class TestWebSocketChat:
    def test_chat_frame_is_enqueued_with_the_pipeline_attributes(self, monkeypatch):
        app, _, transport, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "chat", "request_id": "r-1", "body": {"prompt": "hi", "session_id": "s1"}})
            ack = websocket.receive_json()

        assert ack["type"] == "CHAT_QUEUED"
        assert ack["status"] == "SUCCESS"
        assert ack["request_id"] == "r-1"
        assert ack["user_id"] == "user-1"

        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)
        # No return address on the message: USER_ID doubles as the WS-entered marker, and the
        # connection store owns where to deliver (spec §2 invariant).
        assert message.attributes == {ATTR_REQUEST_ID: "r-1", ATTR_USER_ID: "user-1"}
        assert message.group_id == "s1"
        assert message.dedup_id == "r-1"
        assert json.loads(message.body) == {"prompt": "hi", "session_id": "s1"}

    def test_route_omitted_defaults_to_chat(self, monkeypatch):
        app, _, transport, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"body": {"prompt": "hi", "session_id": "s1"}})
            assert websocket.receive_json()["type"] == "CHAT_QUEUED"
        assert len(transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)) == 1

    def test_configured_chat_route_is_honored(self, monkeypatch):
        app, _, _, _ = _ws_app(monkeypatch, chat_route="converse")
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "converse", "body": {"prompt": "hi", "session_id": "s1"}})
            assert websocket.receive_json()["type"] == "CHAT_QUEUED"

    @pytest.mark.parametrize(
        "frame,expected",
        [
            ({"route": "chat"}, "body is required"),
            ({"route": "chat", "body": {"prompt": "hi"}}, "session_id is required"),
            # A promptless body fails BaseRunRequest validation before the chat handler sees it.
            ({"route": "chat", "body": {"session_id": "s1"}}, "prompt"),
        ],
    )
    def test_chat_validation_failures_send_system_frames(self, monkeypatch, frame, expected):
        app, _, transport, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json(frame)
            reply = websocket.receive_json()

        assert reply["status"] == "FAILED"
        assert reply["type"] == "SYSTEM_RESPONSE"
        assert expected in reply["message"]
        assert transport.create_consumer(QueueName.INPUT).fetch(1, 0.05) == []

    def test_non_json_frame_is_rejected(self, monkeypatch):
        app, _, _, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_text("not json")
            reply = websocket.receive_json()
        assert reply["status"] == "FAILED"
        assert "not JSON" in reply["message"]

    def test_unknown_route_is_reported(self, monkeypatch):
        app, _, _, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "nope"})
            reply = websocket.receive_json()
        assert reply == {"status": "FAILED", "message": "Route 'nope' not found", "type": "SYSTEM_RESPONSE"}


class TestCustomRoutes:
    def test_sync_route_result_is_sent_as_system_response(self, monkeypatch):
        @PipelineWebSocketHandler.register("status")
        def status_route(msg):
            return {"status": "SUCCESS", "echo": msg["message"]["value"], "user": msg["user_id"]}

        app, _, _, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "status", "value": 42})
            reply = websocket.receive_json()

        assert reply == {"status": "SUCCESS", "echo": 42, "user": "user-1", "type": "SYSTEM_RESPONSE"}

    def test_async_route_and_none_result_sends_nothing(self, monkeypatch):
        seen = []

        @PipelineWebSocketHandler.register("fire-and-forget")
        async def fire_route(msg):
            seen.append(msg["message"])
            return None

        app, _, _, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "fire-and-forget", "n": 1})
            # A follow-up frame proves no response was sent for the first one.
            websocket.send_json({"route": "nope"})
            reply = websocket.receive_json()

        assert reply["message"] == "Route 'nope' not found"
        assert seen == [{"route": "fire-and-forget", "n": 1}]

    def test_raising_route_reports_a_generic_error(self, monkeypatch):
        @PipelineWebSocketHandler.register("broken")
        def broken_route(msg):
            raise RuntimeError("secret internals")

        app, _, _, _ = _ws_app(monkeypatch)
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "broken"})
            reply = websocket.receive_json()

        assert reply == {"status": "FAILED", "message": "Route handler encountered an error", "type": "SYSTEM_RESPONSE"}

    def test_duplicate_registration_keeps_the_first(self):
        @PipelineWebSocketHandler.register("dup")
        def first(msg):
            return {"who": "first"}

        @PipelineWebSocketHandler.register("dup")
        def second(msg):
            return {"who": "second"}

        assert PipelineWebSocketHandler._custom_routes["dup"] is first

    @pytest.mark.parametrize(
        "route,match",
        [
            ("", "non-empty"),
            ("/ws/status", "bare route name"),
            ("chat", "built-in chat route"),
            ("bad route!", "only letters"),
        ],
    )
    def test_route_name_validation(self, route, match):
        with pytest.raises(ValueError, match=match):
            PipelineWebSocketHandler.register(route)


class TestWebSocketGateway:
    def test_validator_is_mandatory(self, monkeypatch):
        _use_config(monkeypatch, mode=ExecutionMode.ASYNC)
        with pytest.raises(ValueError, match="auth_validator is required"):
            WebSocketGateway.run(auth_validator=None)

    def test_in_memory_transport_is_rejected(self, monkeypatch):
        """The standalone gateway is broker-only (an in_memory queue cannot reach a separate
        gateway process); the error points at the co-hosted single-process topology."""
        config = _use_config(monkeypatch, mode=ExecutionMode.ASYNC, push_auth_token="s3cret")
        with pytest.raises(AKConfigError, match="in_memory.*IOHandler"):
            WebSocketGateway._validate(_Validator(), "in_memory", config)

    def test_rest_modes_are_rejected(self, monkeypatch):
        config = _use_config(monkeypatch, mode=ExecutionMode.REST_SYNC, push_auth_token="s3cret")
        with pytest.raises(AKConfigError, match="ASYNC/STREAM"):
            WebSocketGateway._validate(_Validator(), "nats", config)

    def test_missing_push_token_is_rejected(self, monkeypatch):
        config = _use_config(monkeypatch, mode=ExecutionMode.ASYNC)
        with pytest.raises(AKConfigError, match="push_auth_token"):
            WebSocketGateway._validate(_Validator(), "nats", config)

    def test_valid_config_passes_validation(self, monkeypatch):
        config = _use_config(monkeypatch, mode=ExecutionMode.STREAM, push_auth_token="s3cret")
        WebSocketGateway._validate(_Validator(), "nats", config)

    def test_push_port_differing_from_api_port_is_rejected(self, monkeypatch):
        """The built-in gateway serves /ws and /internal/push on one server bound to api.port:
        a different advertised push port would record endpoints nothing answers, so it fails
        fast (push_port exists for custom gateways with their own separate push listener)."""
        config = _use_config(monkeypatch, mode=ExecutionMode.ASYNC, push_auth_token="s3cret", push_port=9001, api_port=8000)
        with pytest.raises(AKConfigError, match="push_port"):
            WebSocketGateway._validate(_Validator(), "nats", config)

    def test_push_port_matching_api_port_passes(self, monkeypatch):
        config = _use_config(monkeypatch, mode=ExecutionMode.ASYNC, push_auth_token="s3cret", push_port=8000, api_port=8000)
        WebSocketGateway._validate(_Validator(), "nats", config)

    def test_app_serves_health_ws_and_push(self, monkeypatch):
        _use_config(monkeypatch, mode=ExecutionMode.ASYNC, push_auth_token="s3cret")
        app = WebSocketGateway._build_app(
            PipelineWebSocketHandler(auth_validator=_Validator(), registry=LocalConnectionRegistry(), connection_store=_store()),
            PushEndpointHandler(registry=LocalConnectionRegistry()),
        )
        client = TestClient(app)
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post(PUSH_PATH, json={"connection_id": "x", "message": {}}).status_code == 401
        with client.websocket_connect(f"{WS_PATH}?token=good"):
            pass


def _drain(transport, queue, process, expect, timeout=5.0):
    """Drive one consumer the way its ConsumerLoop thread would, until `expect` messages are done."""
    consumer = transport.create_consumer(queue)
    processed = 0
    deadline = time.monotonic() + timeout
    while processed < expect and time.monotonic() < deadline:
        for message in consumer.fetch(10, 0.05):
            process(message)
            consumer.ack(message)
            processed += 1
    assert processed == expect, f"drained {processed}/{expect} messages from {queue}"


class TestEndToEndOverInMemory:
    """The iteration's first verify gate: single-process ASYNC and STREAM over in_memory."""

    def test_async_chat_reply_reaches_the_websocket(self, monkeypatch):
        app, registry, transport, store = _ws_app(monkeypatch, mode=ExecutionMode.ASYNC)

        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (200, {"result": "hello from agent", "session_id": "s1"})
        runner = AgentRunner(transport=transport, chat_service=chat_service)
        responder = ResponseHandler(transport=transport, ws_handler=PodPushWebSocketHandler(connection_store=store, registry=registry))

        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "chat", "request_id": "r-1", "body": {"prompt": "hi", "session_id": "s1"}})
            assert websocket.receive_json()["type"] == "CHAT_QUEUED"

            _drain(transport, QueueName.INPUT, runner.process, expect=1)
            _drain(transport, QueueName.OUTPUT, responder.process, expect=1)

            reply = websocket.receive_json()

        assert reply == {"result": "hello from agent", "session_id": "s1", "type": "CHAT_RESPONSE"}

    def test_stream_chunks_reach_the_websocket_in_order(self, monkeypatch):
        app, registry, transport, store = _ws_app(monkeypatch, mode=ExecutionMode.STREAM)

        chunks = [{"delta": "he", "session_id": "s1"}, {"delta": "llo", "session_id": "s1"}, {"done": True, "session_id": "s1"}]
        chat_service = MagicMock()
        chat_service.process_stream_chat_sync.return_value = iter([json.dumps(chunk) for chunk in chunks])
        runner = StreamAgentRunner(transport=transport, chat_service=chat_service)
        responder = ResponseHandler(transport=transport, ws_handler=PodPushWebSocketHandler(connection_store=store, registry=registry))

        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            websocket.send_json({"route": "chat", "request_id": "r-1", "body": {"prompt": "hi", "session_id": "s1"}})
            assert websocket.receive_json()["type"] == "CHAT_QUEUED"

            _drain(transport, QueueName.INPUT, runner.process, expect=1)
            _drain(transport, QueueName.OUTPUT, responder.process, expect=3)

            received = [websocket.receive_json() for _ in chunks]

        assert received == [{**chunk, "type": "STREAM_CHUNK"} for chunk in chunks]


class _RoutingPushClient:
    """Routes pod-to-pod POSTs to the TestClient of the gateway 'pod' owning that endpoint."""

    def __init__(self, pods):
        self._pods = pods  # endpoint prefix -> TestClient

    def post(self, url, json=None, headers=None):
        for prefix, client in self._pods.items():
            if url.startswith(prefix):
                return client.post(url[len(prefix) :], json=json, headers=headers)
        raise AssertionError(f"no gateway pod serves {url}")


class TestEndToEndAcrossGatewayPods:
    """The iteration's second verify gate: delivery follows the user's connections across
    gateway 'pods' sharing one connection store, over the authenticated push endpoint."""

    def _gateway(self, monkeypatch, pod_ip, store, transport):
        monkeypatch.setenv("AK_POD_IP", pod_ip)
        registry = LocalConnectionRegistry()
        handler = PipelineWebSocketHandler(auth_validator=_Validator(), registry=registry, transport=transport, connection_store=store)
        app = FastAPI()
        app.include_router(handler.get_router())
        app.include_router(PushEndpointHandler(registry=registry).get_router())
        return TestClient(app)

    def test_reply_lands_on_whichever_pod_holds_the_user(self, monkeypatch):
        _use_config(monkeypatch, mode=ExecutionMode.ASYNC, push_auth_token="s3cret")
        # A broker-shaped topology: endpoints are real addresses, not the local sentinel.
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "nats"))

        store = _store()
        transport = InMemoryTransport()  # stands in for the broker; injected everywhere
        gw1 = self._gateway(monkeypatch, "gw1", store, transport)
        gw2 = self._gateway(monkeypatch, "gw2", store, transport)
        monkeypatch.setattr(ws_push, "_pooled_client", lambda: _RoutingPushClient({"http://gw1:8000": gw1, "http://gw2:8000": gw2}))

        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (200, {"result": "routed", "session_id": "s1"})
        runner = AgentRunner(transport=transport, chat_service=chat_service)
        # The responder lives in an "IO pod": empty local registry, only the store to go by.
        responder = ResponseHandler(
            transport=transport, ws_handler=PodPushWebSocketHandler(connection_store=store, registry=LocalConnectionRegistry())
        )

        def _round_trip(websocket):
            websocket.send_json({"route": "chat", "body": {"prompt": "hi", "session_id": "s1"}})
            assert websocket.receive_json()["type"] == "CHAT_QUEUED"
            _drain(transport, QueueName.INPUT, runner.process, expect=1)
            _drain(transport, QueueName.OUTPUT, responder.process, expect=1)
            return websocket.receive_json()

        # Connected to gateway pod 1: the push endpoint on gw1 delivers.
        with gw1.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            assert store.get_endpoints("user-1") == {connection: "http://gw1:8000" for connection in store.get_connections("user-1")}
            assert _round_trip(websocket) == {"result": "routed", "session_id": "s1", "type": "CHAT_RESPONSE"}

        # The user reconnects to gateway pod 2: the same flow now lands there, no reconfiguration.
        with gw2.websocket_connect(f"{WS_PATH}?token=good") as websocket:
            assert _round_trip(websocket) == {"result": "routed", "session_id": "s1", "type": "CHAT_RESPONSE"}
