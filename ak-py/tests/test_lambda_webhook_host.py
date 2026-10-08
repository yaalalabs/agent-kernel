"""LambdaWebhookHost: serving a WebhookRESTRequestHandler from routes registered with Lambda.register (#760, part 2)."""

import asyncio
import json
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReply, AgentRequestText
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.aklambda import Lambda
from agentkernel.integration.adapter.base import InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter, Source
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.pipeline.envelope import ATTR_INTEGRATION, QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

ADAPTER_NAME = "byo_pkg.FakeOutboundAdapter"
ROUTER_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"
BASE_PATH_ENV = {"API_BASE_PATH": "api", "API_VERSION": "v1", "AGENT_ENDPOINT": "chat"}

META_ENV = {
    "whatsapp": {"AK_WHATSAPP__ACCESS_TOKEN": "token", "AK_WHATSAPP__PHONE_NUMBER_ID": "phone-1", "AK_WHATSAPP__VERIFY_TOKEN": "verify-me"},
    "messenger": {"AK_MESSENGER__ACCESS_TOKEN": "token", "AK_MESSENGER__VERIFY_TOKEN": "verify-me"},
    "instagram": {"AK_INSTAGRAM__ACCESS_TOKEN": "token", "AK_INSTAGRAM__VERIFY_TOKEN": "verify-me"},
    "telegram": {"AK_TELEGRAM__BOT_TOKEN": "bot-token"},
}
SECRET_SETTING = {
    "whatsapp": ("AK_WHATSAPP__APP_SECRET", "whatsapp.app_secret"),
    "messenger": ("AK_MESSENGER__APP_SECRET", "messenger.app_secret"),
    "instagram": ("AK_INSTAGRAM__APP_SECRET", "instagram.app_secret"),
    "telegram": ("AK_TELEGRAM__WEBHOOK_SECRET", "telegram.webhook_secret"),
}


class FakeOutboundAdapter(OutboundAdapter):
    """Records what the edge asked it to do."""

    name = ADAPTER_NAME
    acknowledged: List[Dict[str, str]] = []

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:  # pragma: no cover - not exercised here
        raise AssertionError("the edge must never deliver")

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:  # pragma: no cover - not exercised here
        raise AssertionError("the edge must never deliver")

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        FakeOutboundAdapter.acknowledged.append(dict(reply_context))
        return {"ack_ts": "ack-1"}


def _inbound(**overrides) -> InboundRequest:
    defaults = dict(
        session_id="s1", request_id="r1", requests=[AgentRequestText(prompt="hi")], prompt="hi", user_id="u1", reply_context={"channel": "C9"}
    )
    return InboundRequest(**{**defaults, **overrides})


class FakeInboundAdapter(InboundAdapter):
    name = ADAPTER_NAME
    source = Source.WEBHOOK
    webhook_path = "/fake/webhook"

    def __init__(self, requests: Optional[List[InboundRequest]] = None, response: Any = None, secret: Optional[str] = None):
        self._requests = requests if requests is not None else [_inbound()]
        self._response = response
        self._secret = secret
        self.loops: List[asyncio.AbstractEventLoop] = []

    async def verify(self, raw) -> None:
        if self._secret and raw.headers.get("x-secret") != self._secret:
            raise HTTPException(status_code=403, detail="Invalid secret token")

    async def parse(self, raw) -> InboundParseResult:
        self.loops.append(asyncio.get_running_loop())
        return InboundParseResult(requests=list(self._requests), response=self._response)


class ChallengingInboundAdapter(FakeInboundAdapter):
    challenge_path = "/fake/webhook"

    async def challenge(self, raw) -> Any:
        return int(raw.query_params["hub.challenge"])


def _handler(adapter: Optional[InboundAdapter] = None, transport: Optional[InMemoryTransport] = None) -> WebhookRESTRequestHandler:
    return WebhookRESTRequestHandler(adapter or FakeInboundAdapter(), producer=IntegrationProducer(transport or InMemoryTransport()))


def _event(method: str = "POST", path: str = "/api/v1/fake/webhook", headers: Optional[dict] = None, query: Optional[dict] = None, body: str = "{}"):
    return {
        "httpMethod": method,
        "path": path,
        "headers": headers or {"Host": "abc.execute-api.us-east-1.amazonaws.com"},
        "queryStringParameters": query,
        "body": body,
        "isBase64Encoded": False,
    }


def _drain(transport: InMemoryTransport):
    return transport.create_consumer(QueueName.INPUT).fetch(10, 0.2)


def _host(handler: WebhookRESTRequestHandler):
    from agentkernel.deployment.aws.serverless.core.webhook_host import LambdaWebhookHost

    return LambdaWebhookHost(handler)


def _make_inbound(platform: str) -> InboundAdapter:
    if platform == "whatsapp":
        from agentkernel.integration.whatsapp.adapter import WhatsAppInboundAdapter

        return WhatsAppInboundAdapter()
    if platform == "messenger":
        from agentkernel.integration.messenger.adapter import MessengerInboundAdapter

        return MessengerInboundAdapter()
    if platform == "instagram":
        from agentkernel.integration.instagram.adapter import InstagramInboundAdapter

        return InstagramInboundAdapter()
    from agentkernel.integration.telegram.adapter import TelegramInboundAdapter

    return TelegramInboundAdapter()


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    """A deployment LambdaWebhookHost accepts: rest_async on sqs, with the base-path variables set."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_EXECUTION__MODE", "rest_async")
    monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", "sqs")
    for key, value in BASE_PATH_ENV.items():
        monkeypatch.setenv(key, value)
    AKConfig._reset()
    InMemoryTransport.reset()
    FakeOutboundAdapter.acknowledged = []
    IntegrationAdapterFactory.reset()
    IntegrationAdapterFactory._cache[ADAPTER_NAME] = FakeOutboundAdapter()
    Lambda._router = None
    Lambda._config = None
    _reset_host_loop()
    yield
    _reset_host_loop()
    Lambda._router = None
    Lambda._config = None
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    AKConfig._reset()


def _reset_host_loop():
    try:
        from agentkernel.deployment.aws.serverless.core.webhook_host import LambdaWebhookHost
    except ImportError:
        return
    if LambdaWebhookHost._loop is not None and not LambdaWebhookHost._loop.is_closed():
        LambdaWebhookHost._loop.close()
    LambdaWebhookHost._loop = None


@pytest.fixture
def chat_route():
    """A stubbed chat route, so Lambda.handler can build its router without an agent."""
    chat = MagicMock(return_value=(200, {"via": "chat"}))
    endpoints = MagicMock()
    endpoints.get_default_endpoint_info.return_value = ("default_chat_path", "POST", "GET")
    endpoints.get_routes.return_value = {"default_chat_path": {"POST": chat}}
    with patch(f"{ROUTER_MODULE}.DefaultEndpointsHandler", return_value=endpoints):
        yield chat


class TestAdapterAdditions:
    def test_an_adapter_needs_no_verification_settings_by_default(self):
        assert FakeInboundAdapter().missing_verification_settings() == []

    @pytest.mark.parametrize("platform", sorted(SECRET_SETTING))
    def test_a_builtin_names_its_unset_verification_secret(self, monkeypatch, platform):
        for key, value in META_ENV[platform].items():
            monkeypatch.setenv(key, value)
        AKConfig._reset()

        assert _make_inbound(platform).missing_verification_settings() == [SECRET_SETTING[platform][1]]

    @pytest.mark.parametrize("platform", sorted(SECRET_SETTING))
    def test_a_builtin_with_its_secret_set_needs_nothing(self, monkeypatch, platform):
        for key, value in META_ENV[platform].items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv(SECRET_SETTING[platform][0], "s3cret")
        AKConfig._reset()

        assert _make_inbound(platform).missing_verification_settings() == []

    def test_the_webhook_handler_exposes_its_adapter(self):
        adapter = FakeInboundAdapter()
        handler = WebhookRESTRequestHandler(adapter, producer=IntegrationProducer(InMemoryTransport()))

        assert handler.adapter is adapter


class TestRegisteredRoutes:
    """The application registers the host's endpoints with Lambda.register; Lambda.handler dispatches to them."""

    def test_a_webhook_reaches_the_host_and_not_the_chat_route(self, chat_route):
        transport = InMemoryTransport()
        host = _host(_handler(transport=transport))

        @Lambda.register("/fake/webhook", method="POST")
        def fake_webhook(event, context):
            return host.handle(event, context)

        response = Lambda.handler(_event(), None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"status": "ok"}
        chat_route.assert_not_called()
        assert len(_drain(transport)) == 1

    def test_a_rejected_delivery_keeps_its_status(self, chat_route):
        transport = InMemoryTransport()
        host = _host(_handler(FakeInboundAdapter(secret="s3cret"), transport))
        Lambda.register("/fake/webhook", method="POST")(host.handle)

        response = Lambda.handler(_event(headers={"x-secret": "wrong"}), None)

        assert response["statusCode"] == 403 and json.loads(response["body"]) == {"detail": "Invalid secret token"}
        assert _drain(transport) == []

    def test_the_challenge_is_answered_through_the_handler(self, chat_route):
        host = _host(_handler(ChallengingInboundAdapter()))
        Lambda.register("/fake/webhook", method="GET")(host.challenge)

        response = Lambda.handler(_event(method="GET", body=None, query={"hub.challenge": "12345"}), None)

        assert response["statusCode"] == 200 and json.loads(response["body"]) == 12345


class TestEventLoop:
    def test_invocations_share_one_event_loop(self):
        adapter = FakeInboundAdapter(requests=[])
        host = _host(_handler(adapter))

        host.handle(_event(), None)
        host.handle(_event(), None)

        assert len(adapter.loops) == 2 and adapter.loops[0] is adapter.loops[1]

    def test_the_loop_is_never_made_the_threads_current_loop(self):
        outcome = {}

        def _invoke():
            _host(_handler(FakeInboundAdapter(requests=[]))).handle(_event(), None)
            try:
                asyncio.get_event_loop()
                outcome["current_loop"] = True
            except RuntimeError:
                outcome["current_loop"] = False

        worker = threading.Thread(target=_invoke)
        worker.start()
        worker.join()

        assert outcome == {"current_loop": False}

    def test_a_closed_loop_is_replaced(self):
        from agentkernel.deployment.aws.serverless.core.webhook_host import LambdaWebhookHost

        closed = asyncio.new_event_loop()
        closed.close()
        LambdaWebhookHost._loop = closed

        response = _host(_handler(FakeInboundAdapter(requests=[]))).handle(_event(), None)

        assert response["statusCode"] == 200
        assert LambdaWebhookHost._loop is not closed and not LambdaWebhookHost._loop.is_closed()


class TestGuards:
    """Every check runs when the host is built, at module scope, so a broken deployment fails its init."""

    @pytest.mark.parametrize("transport_type", [None, "in_memory", "kafka"])
    def test_a_non_sqs_transport_is_refused(self, monkeypatch, transport_type):
        if transport_type is None:
            monkeypatch.delenv("AK_EXECUTION__QUEUES__TYPE")
        else:
            monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", transport_type)
        AKConfig._reset()

        with pytest.raises(AKConfigError, match="queue_mode") as excinfo:
            _host(_handler())

        assert "execution.queues.type" in str(excinfo.value)

    @pytest.mark.parametrize("mode", ["async", "stream", None])
    def test_a_websocket_or_unset_mode_is_refused(self, monkeypatch, mode):
        if mode is None:
            monkeypatch.delenv("AK_EXECUTION__MODE")
        else:
            monkeypatch.setenv("AK_EXECUTION__MODE", mode)
        AKConfig._reset()

        with pytest.raises(AKConfigError, match="rest_sync or rest_async"):
            _host(_handler())

    @pytest.mark.parametrize("variable", sorted(BASE_PATH_ENV))
    def test_a_missing_base_path_variable_is_refused(self, monkeypatch, variable):
        monkeypatch.delenv(variable)

        with pytest.raises(AKConfigError, match=variable):
            _host(_handler())

    @pytest.mark.parametrize("platform", sorted(SECRET_SETTING))
    def test_an_adapter_without_its_verification_secret_is_refused(self, monkeypatch, platform):
        for key, value in META_ENV[platform].items():
            monkeypatch.setenv(key, value)
        AKConfig._reset()

        with pytest.raises(AKConfigError, match=SECRET_SETTING[platform][1].replace(".", r"\.")):
            _host(_handler(_make_inbound(platform)))

    @pytest.mark.parametrize("platform", sorted(SECRET_SETTING))
    def test_an_adapter_with_its_verification_secret_is_hosted(self, monkeypatch, platform):
        for key, value in META_ENV[platform].items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv(SECRET_SETTING[platform][0], "s3cret")
        AKConfig._reset()

        _host(_handler(_make_inbound(platform)))

    def test_slack_without_its_signing_secret_fails_at_construction(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
        from agentkernel.integration.slack.adapter import SlackInboundAdapter

        with pytest.raises(ValueError, match="signing_secret"):
            SlackInboundAdapter()

    def test_teams_without_its_app_id_fails_at_construction(self):
        from agentkernel.integration.teams.adapter import TeamsInboundAdapter

        with pytest.raises(ValueError):
            TeamsInboundAdapter()

    def test_a_non_webhook_handler_is_refused(self):
        from agentkernel.api.handler import AgentRESTRequestHandler

        with pytest.raises(TypeError, match="WebhookRESTRequestHandler"):
            _host(AgentRESTRequestHandler())


class TestHostMirrorsFastAPI:
    """The cases of test_integration_webhook_handler.py, replayed through the Lambda host."""

    def test_a_parsed_delivery_is_enqueued(self):
        transport = InMemoryTransport()
        assert _host(_handler(transport=transport)).handle(_event(), None)["statusCode"] == 200

        [message] = _drain(transport)
        assert message.attributes[ATTR_INTEGRATION] == ADAPTER_NAME
        assert json.loads(message.body)["session_id"] == "s1"

    def test_every_message_in_a_batched_delivery_is_enqueued(self):
        transport = InMemoryTransport()
        batch = [_inbound(session_id="s1", request_id="r1"), _inbound(session_id="s2", request_id="r2")]
        _host(_handler(FakeInboundAdapter(requests=batch), transport)).handle(_event(), None)

        assert sorted(m.group_id for m in _drain(transport)) == ["s1", "s2"]

    def test_the_acknowledgement_extends_the_reply_context(self):
        transport = InMemoryTransport()
        _host(_handler(transport=transport)).handle(_event(), None)

        assert FakeOutboundAdapter.acknowledged == [{"channel": "C9"}]
        [message] = _drain(transport)
        assert message.attributes["reply_ack_ts"] == "ack-1"

    def test_an_ignored_delivery_succeeds_without_enqueueing(self):
        transport = InMemoryTransport()
        response = _host(_handler(FakeInboundAdapter(requests=[]), transport)).handle(_event(), None)

        assert response["statusCode"] == 200 and json.loads(response["body"]) == {"status": "ok"}
        assert _drain(transport) == []
        assert FakeOutboundAdapter.acknowledged == []

    def test_an_sdk_owned_response_is_returned_verbatim(self):
        from fastapi.responses import JSONResponse

        adapter = FakeInboundAdapter(requests=[], response=JSONResponse({"challenge": "abc"}, status_code=201))
        response = _host(_handler(adapter)).handle(_event(), None)

        assert response["statusCode"] == 201 and json.loads(response["body"]) == {"challenge": "abc"}

    def test_verification_failure_rejects_before_enqueueing(self):
        transport = InMemoryTransport()
        host = _host(_handler(FakeInboundAdapter(secret="s3cret"), transport))

        response = host.handle(_event(headers={"x-secret": "wrong"}), None)

        assert response["statusCode"] == 403 and json.loads(response["body"]) == {"detail": "Invalid secret token"}
        assert _drain(transport) == []
        assert FakeOutboundAdapter.acknowledged == []

    def test_an_enqueue_failure_is_a_generic_500(self):
        class BrokenProducer(IntegrationProducer):
            def enqueue(self, adapter_name, request):
                raise RuntimeError("broker unreachable")

        handler = WebhookRESTRequestHandler(FakeInboundAdapter(), producer=BrokenProducer(InMemoryTransport()))
        response = _host(handler).handle(_event(), None)

        assert response["statusCode"] == 500
        assert response["body"] == "Internal Server Error"
