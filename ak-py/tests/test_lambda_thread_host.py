"""LambdaThreadHost: Conversation Thread Support on the request-handler Lambda (#879, phase 2)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import ScheduleSpec
from agentkernel.core.multimodal.storage import AttachmentStorageManager
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler
from agentkernel.deployment.aws.serverless.aklambda import Lambda
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.integration.thread import ConversationThreadManager, ThreadNamingStrategy, ThreadRequestHandler
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore
from agentkernel.pipeline.envelope import ATTR_THREAD
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

AGENT_NAME = "lambda-thread-agent"
ROUTER_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"
CHAT_PATH = "/api/v1/chat"
BASE_PATH_ENV = {"API_BASE_PATH": "api", "API_VERSION": "v1", "AGENT_ENDPOINT": "chat"}
# A dotted path passes the guard's in_memory check while keeping the test offline.
IN_MEMORY_STORE_PATH = "agentkernel.integration.thread.store.in_memory.InMemoryThreadStore"


class EchoNaming(ThreadNamingStrategy):
    def generate_name(self, prompt: str) -> str:
        return (prompt or "").strip()


def _reset_loops():
    from agentkernel.deployment.aws.serverless.core.integration.thread import LambdaThreadHost
    from agentkernel.deployment.aws.serverless.core.integration.webhook import LambdaWebhookHost

    for host in (LambdaThreadHost, LambdaWebhookHost):
        if host._loop is not None and not host._loop.is_closed():
            host._loop.close()
        host._loop = None


def _reset_globals():
    Lambda._router = None
    Lambda._config = None
    SQSHandler._config = None
    SQSHandler._input_queue_url = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    InMemoryTransport.reset()
    _reset_loops()
    AKConfig._reset()


def _configure(monkeypatch, mode: str = "rest_sync", thread_type: str | None = IN_MEMORY_STORE_PATH, queue_url: str | None = "https://sqs/in.fifo"):
    monkeypatch.setenv("AK_EXECUTION__MODE", mode)
    if queue_url:
        monkeypatch.setenv("AK_EXECUTION__QUEUES__INPUT__URL", queue_url)
    else:
        monkeypatch.delenv("AK_EXECUTION__QUEUES__INPUT__URL", raising=False)
    _reset_globals()
    if thread_type:
        AKConfig.get().thread = _ThreadStoreConfig(type=thread_type)
        ConversationThreadManager.set_naming_strategy(EchoNaming())


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    """A deployment LambdaThreadHost accepts: rest_sync on sqs with an input queue and the base-path variables."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", "sqs")
    monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__TYPE", "dynamodb")
    for key, value in BASE_PATH_ENV.items():
        monkeypatch.setenv(key, value)
    _configure(monkeypatch)
    yield
    _reset_globals()


@pytest.fixture
def store():
    """The response store the chat route reads; rest_sync finds the runner's reply at once."""
    store = MagicMock()
    store.get_record_with_retry.return_value = {"body": {"result": "ok", "session_id": "s1"}, "status_code": 200}
    with patch(f"{ROUTER_MODULE}.ResponseStoreFactory.create", return_value=store), patch(f"{ROUTER_MODULE}.ChatService"):
        yield store


@pytest.fixture
def send():
    with patch(f"{ROUTER_MODULE}.SQSHandler.send_message_to_input_queue", return_value={"MessageId": "m1"}) as send:
        yield send


def _host(handler=None):
    from agentkernel.deployment.aws.serverless.core.integration.thread import LambdaThreadHost

    return LambdaThreadHost(handler if handler is not None else ThreadRequestHandler())


def _register(host):
    """The routes an application registers, as in the thread-openai example."""
    Lambda.register("/threads", method="GET")(host.list_threads)
    Lambda.register("/threads/{session_id}", method="GET")(host.get_thread)


def _chat_event(method: str = "POST", **body) -> dict:
    payload = {"request_id": "req-1", "prompt": "hello", "session_id": "s1", "user_id": "u1", "agent": AGENT_NAME, **body}
    payload = {k: v for k, v in payload.items() if v is not None}
    return {"httpMethod": method, "path": CHAT_PATH, "headers": {}, "body": json.dumps(payload), "isBase64Encoded": False}


def _read_event(path: str, query: dict | None = None, principal: str | None = None, session_id: str | None = None) -> dict:
    event = {
        "httpMethod": "GET",
        "path": f"/api/v1{path}",
        "resource": "/api/v1/threads/{session_id}" if session_id else "/api/v1/threads",
        "headers": {"Host": "abc.execute-api.us-east-1.amazonaws.com"},
        "queryStringParameters": query,
        "body": None,
        "isBase64Encoded": False,
    }
    if session_id:
        event["pathParameters"] = {"session_id": session_id}
    if principal:
        event["requestContext"] = {"authorizer": {"principalId": principal}}
    return event


def _sent_attributes(send) -> dict:
    return {a.name: a.value for a in send.call_args.kwargs["custom_message_attributes"] or []}


def _thread_count() -> int:
    return len(InMemoryThreadStore._threads)


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def _open_thread(session_id: str, user_id: str):
    manager = ConversationThreadManager.get()
    manager.get_or_create_thread(session_id=session_id, user_id=user_id, group_id=None, name=session_id, first_prompt="hi")
    manager.append_message(session_id, "user", "hi")


class TestChat:
    @pytest.mark.parametrize("mode", ["rest_sync", "rest_async"])
    def test_the_user_message_is_recorded_and_the_send_is_marked(self, monkeypatch, store, send, mode):
        _configure(monkeypatch, mode=mode)
        _host()

        response = Lambda.handler(_chat_event(), None)

        assert response["statusCode"] == 200
        expected = {"result": "ok", "session_id": "s1"} if mode == "rest_sync" else {"status": "ACCEPTED", "request_id": "req-1"}
        assert _body(response) == expected
        assert _sent_attributes(send) == {ATTR_THREAD: "1"}
        [message] = ConversationThreadManager.get().get_messages("s1").messages
        assert (message.role, message.content) == ("user", "hello")

    @pytest.mark.parametrize(
        "body,error",
        [
            ({"user_id": None}, "user_id"),
            ({"prompt": ""}, "No prompt provided"),
            ({"images": [{"image_data": "aGVsbG8=", "name": "a.png", "mime_type": "image/png"}]}, "multimodal"),
        ],
        ids=["no-user-id", "no-prompt", "attachments-multimodal-off"],
    )
    def test_a_rejection_answers_400_and_writes_and_sends_nothing(self, store, send, body, error):
        _host()

        response = Lambda.handler(_chat_event(**body), None)

        assert response["statusCode"] == 400
        assert error in _body(response)["error"]
        assert _body(response)["session_id"] == "s1"
        assert _thread_count() == 0
        send.assert_not_called()

    def test_a_missing_session_id_is_still_the_generic_500_and_skips_the_hook(self, store, send):
        host = _host()

        with patch.object(host._handler, "prepare_for_queue") as prepare:
            response = Lambda.handler(_chat_event(session_id=None), None)

        assert response["statusCode"] == 500
        prepare.assert_not_called()
        send.assert_not_called()

    def test_a_schedule_block_records_nothing_and_is_unmarked(self, store, send):
        _host()

        Lambda.handler(_chat_event(schedule=ScheduleSpec(at="2999-01-01T00:00:00Z").model_dump(exclude_none=True)), None)

        assert _sent_attributes(send) == {}
        assert _thread_count() == 0

    def test_base64_images_travel_as_references(self, store, send):
        AKConfig.get().multimodal.enabled = True
        with patch.object(AttachmentStorageManager, "store_is_shared", return_value=True):
            _host()

        image = {"image_data": "aGVsbG8=", "name": "a.png", "mime_type": "image/png"}
        assert Lambda.handler(_chat_event(images=[image]), None)["statusCode"] == 200

        sent = send.call_args.kwargs["message_body"]
        assert "images" not in sent
        assert [r["type"] for r in sent["requests"]] == ["text", "attachment_ref"]
        assert "aGVsbG8=" not in json.dumps(sent)

    def test_the_rest_async_poll_is_unchanged(self, monkeypatch, store, send):
        _configure(monkeypatch, mode="rest_async")
        store.get_record_with_retry.return_value = {"body": {"result": "done"}, "status_code": 200}
        _host()

        response = Lambda.handler(_chat_event(method="GET"), None)

        assert (response["statusCode"], _body(response)) == (200, {"result": "done"})
        send.assert_not_called()
        assert _thread_count() == 0


class TestReadRoutes:
    @pytest.fixture(autouse=True)
    def _routes(self, store):
        _register(_host())
        _open_thread("s1", "u1")
        _open_thread("s2", "u2")

    def test_list_without_an_authorizer_is_open_and_filters_by_user_id(self):
        response = Lambda.handler(_read_event("/threads", query={"user_id": "u2"}), None)

        assert response["statusCode"] == 200
        assert [t["session_id"] for t in _body(response)["threads"]] == ["s2"]

    def test_list_is_forced_to_the_authorized_user(self):
        response = Lambda.handler(_read_event("/threads", query={"user_id": "u2"}, principal="u1"), None)

        assert [t["session_id"] for t in _body(response)["threads"]] == ["s1"]

    def test_get_reads_the_path_parameter(self):
        response = Lambda.handler(_read_event("/threads/s1", session_id="s1"), None)

        assert response["statusCode"] == 200
        assert [m["content"] for m in _body(response)["messages"]] == ["hi"]

    def test_get_of_another_users_thread_is_403(self):
        response = Lambda.handler(_read_event("/threads/s2", session_id="s2", principal="u1"), None)

        assert response["statusCode"] == 403

    def test_get_of_an_unknown_thread_is_404(self):
        response = Lambda.handler(_read_event("/threads/nope", session_id="nope"), None)

        assert response["statusCode"] == 404
        assert "detail" in _body(response)

    def test_thread_support_off_is_404(self):
        with patch("agentkernel.integration.thread.thread_chat.ConversationThreadManager.get", return_value=None):
            response = Lambda.handler(_read_event("/threads"), None)

        assert response["statusCode"] == 404

    @pytest.mark.parametrize("path,session_id", [("/threads", None), ("/threads/s1", "s1")])
    def test_a_non_integer_limit_is_400(self, path, session_id):
        response = Lambda.handler(_read_event(path, query={"limit": "ten"}, session_id=session_id), None)

        assert response["statusCode"] == 400
        assert "limit" in _body(response)["detail"]

    def test_cursor_paging(self):
        manager = ConversationThreadManager.get()
        manager.append_message("s1", "assistant", "hello back")

        first = _body(Lambda.handler(_read_event("/threads/s1", query={"limit": "1"}, session_id="s1"), None))
        second = _body(Lambda.handler(_read_event("/threads/s1", query={"limit": "1", "cursor": first["next_cursor"]}, session_id="s1"), None))

        assert [m["content"] for m in first["messages"] + second["messages"]] == ["hi", "hello back"]


class TestColdStart:
    def test_a_non_thread_handler_is_a_type_error(self):
        with pytest.raises(TypeError, match="ThreadRequestHandler only"):
            _host(MagicMock())

    @pytest.mark.parametrize("mode,message_type", [("async", None), ("rest_sync", "delta")])
    def test_a_non_rest_or_delta_deployment_is_rejected(self, monkeypatch, mode, message_type):
        if message_type:
            monkeypatch.setenv("AK_EXECUTION__MESSAGE_TYPE", message_type)
        _configure(monkeypatch, mode=mode)

        with pytest.raises(AKConfigError, match="LambdaThreadHost serves threads"):
            _host()

    def test_a_non_sqs_transport_is_rejected(self, monkeypatch):
        monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", "in_memory")
        _configure(monkeypatch)

        with pytest.raises(AKConfigError, match="needs the sqs queue transport"):
            _host()

    def test_missing_base_path_env_is_rejected(self, monkeypatch):
        monkeypatch.delenv("API_VERSION")

        with pytest.raises(AKConfigError, match="API_VERSION"):
            _host()

    def test_an_authoriser_is_rejected(self):
        with pytest.raises(AKConfigError, match="without an Authoriser"):
            _host(ThreadRequestHandler(authoriser=MagicMock()))

    def test_an_unshared_attachment_store_is_rejected_with_multimodal_on(self):
        AKConfig.get().multimodal.enabled = True

        with pytest.raises(AKConfigError, match="multimodal.storage_type"):
            _host()

    def test_an_in_memory_thread_store_is_rejected(self, monkeypatch):
        _configure(monkeypatch, thread_type="IN_MEMORY")

        with pytest.raises(AKConfigError, match="thread.type 'in_memory'"):
            _host()

    def test_no_thread_block_fails_before_the_host_exists(self, monkeypatch):
        _configure(monkeypatch, thread_type=None)

        with pytest.raises(ValueError, match="'thread' block"):
            ThreadRequestHandler()

    def test_non_queue_mode_is_rejected(self, monkeypatch, store):
        _configure(monkeypatch, queue_url=None)

        with pytest.raises(AKConfigError, match="requires queue mode"):
            _host()

    def test_a_second_hook_is_rejected(self, store):
        _host()

        with pytest.raises(ValueError, match="already set"):
            _host()


def test_a_webhook_host_and_a_thread_host_serve_their_routes_in_one_process(monkeypatch, store, send):
    from test_lambda_webhook_host import ADAPTER_NAME, FakeInboundAdapter, FakeOutboundAdapter

    from agentkernel.deployment.aws.serverless.core.integration.webhook import LambdaWebhookHost

    monkeypatch.setitem(IntegrationAdapterFactory._cache, ADAPTER_NAME, FakeOutboundAdapter())
    transport = InMemoryTransport()
    webhook = LambdaWebhookHost(WebhookRESTRequestHandler(FakeInboundAdapter(), producer=IntegrationProducer(transport)))
    Lambda.register("/fake/webhook", method="POST")(webhook.handle)
    _register(_host())

    webhook_event = {"httpMethod": "POST", "path": "/api/v1/fake/webhook", "headers": {"Host": "h"}, "body": "{}", "isBase64Encoded": False}
    assert Lambda.handler(webhook_event, None)["statusCode"] == 200
    assert Lambda.handler(_chat_event(), None)["statusCode"] == 200
    assert _thread_count() == 1
    assert Lambda.handler(_read_event("/threads"), None)["statusCode"] == 200
