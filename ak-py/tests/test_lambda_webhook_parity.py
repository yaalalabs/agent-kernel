"""The Lambda webhook host answers exactly as the FastAPI route does, for every built-in webhook adapter (#760).

Each delivery goes to two places: an API Gateway event through LambdaWebhookHost, and an HTTP
request through the FastAPI route (TestClient over WebhookRESTRequestHandler.get_router()). Both
must give the same status, the same body bytes, and the same enqueued message.

The Meta and Telegram deliveries come from the IntegrationAdapterContract subclasses, so they have
one definition. Slack's and Teams' contract hooks bypass their SDK's dispatch, so their deliveries
here are HTTP-level: a signed Bolt request, and a Bot Framework activity with process_activity
stubbed on the adapter instance.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
import test_integration_adapter_contract as contract
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.core.config import AKConfig
from agentkernel.deployment.aws.serverless.core.webhook_host import LambdaWebhookHost
from agentkernel.integration.adapter.base import InboundAdapter, OutboundAdapter
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

BASE_PATH = "/api/v1"
SLACK_SIGNING_SECRET = "test-signing-secret"
BOT_ID = "B_BOT"


class _EdgeOutboundAdapter(OutboundAdapter):
    """Stands in for each platform's outbound half at the edge: acknowledges, never delivers."""

    name = "edge"

    async def deliver(self, reply, reply_context) -> None:  # pragma: no cover - never reached at the edge
        raise AssertionError("the edge must never deliver")

    async def deliver_error(self, message, reply_context) -> None:  # pragma: no cover - never reached at the edge
        raise AssertionError("the edge must never deliver")

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        return {"ack_ts": "ack-1"}


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    """A deployment LambdaWebhookHost accepts: rest_async on sqs, with the base-path variables set."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_EXECUTION__MODE", "rest_async")
    monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", "sqs")
    for key, value in {"API_BASE_PATH": "api", "API_VERSION": "v1", "AGENT_ENDPOINT": "chat"}.items():
        monkeypatch.setenv(key, value)
    AKConfig._reset()
    IntegrationAdapterFactory.reset()
    for name in ("slack", "teams", "telegram", "whatsapp", "messenger", "instagram"):
        IntegrationAdapterFactory._cache[name] = _EdgeOutboundAdapter()
    InMemoryTransport.reset()
    yield
    if LambdaWebhookHost._loop is not None:
        LambdaWebhookHost._loop.close()
    LambdaWebhookHost._loop = None
    InMemoryTransport.reset()
    IntegrationAdapterFactory.reset()
    AKConfig._reset()


def _configure(monkeypatch, env: Dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    AKConfig._reset()


Delivery = Tuple[bytes, Dict[str, str], Optional[Dict[str, str]]]
Answer = Tuple[int, bytes, List[Tuple[str, Dict[str, str], Optional[str], Optional[str]]]]


def _drain() -> list:
    messages = InMemoryTransport().create_consumer(QueueName.INPUT).fetch(10, 0.2)
    return [(message.body, dict(message.attributes), message.group_id, message.dedup_id) for message in messages]


def _through_lambda(adapter: InboundAdapter, method: str, path: str, delivery: Delivery) -> Answer:
    body, headers, query = delivery
    InMemoryTransport.reset()
    host = LambdaWebhookHost(WebhookRESTRequestHandler(adapter, producer=IntegrationProducer(InMemoryTransport())))
    event = {
        "httpMethod": method,
        "path": BASE_PATH + path,
        "headers": headers,
        "queryStringParameters": query,
        "body": body.decode("utf-8") if body else None,
        "isBase64Encoded": False,
    }
    proxy = host.challenge(event, None) if method == "GET" else host.handle(event, None)
    content = base64.b64decode(proxy["body"]) if proxy["isBase64Encoded"] else proxy["body"].encode("utf-8")
    return proxy["statusCode"], content, _drain()


def _through_fastapi(adapter: InboundAdapter, method: str, path: str, delivery: Delivery) -> Answer:
    body, headers, query = delivery
    InMemoryTransport.reset()
    app = FastAPI()
    app.include_router(WebhookRESTRequestHandler(adapter, producer=IntegrationProducer(InMemoryTransport())).get_router())
    response = TestClient(app).request(method, path, content=body, headers=headers, params=query)
    return response.status_code, response.content, _drain()


def _assert_parity(adapter: InboundAdapter, method: str, path: str, delivery: Delivery) -> Answer:
    on_lambda = _through_lambda(adapter, method, path, delivery)
    on_fastapi = _through_fastapi(adapter, method, path, delivery)
    assert on_lambda == on_fastapi
    return on_lambda


def _from_fake_request(fake) -> Delivery:
    """The body, headers and query a contract subclass's fake request carries."""
    return asyncio.run(fake.body()), dict(fake.headers), dict(fake.query_params) or None


META = [
    ("whatsapp", contract.TestWhatsAppContract),
    ("messenger", contract.TestMessengerContract),
    ("instagram", contract.TestInstagramContract),
]


class TestMetaParity:
    @pytest.mark.parametrize("platform, contract_class", META)
    def test_a_valid_delivery(self, monkeypatch, platform, contract_class):
        spec = contract_class()
        _configure(monkeypatch, spec.ENV)
        adapter = spec.make_inbound()

        status, _, messages = _assert_parity(adapter, "POST", adapter.webhook_path, _from_fake_request(spec.valid_delivery()))

        assert status == 200 and len(messages) == 1

    @pytest.mark.parametrize("platform, contract_class", META)
    def test_an_unauthentic_delivery(self, monkeypatch, platform, contract_class):
        spec = contract_class()
        _configure(monkeypatch, spec.ENV)
        adapter = spec.make_inbound()

        status, _, messages = _assert_parity(adapter, "POST", adapter.webhook_path, _from_fake_request(spec.unauthentic_delivery()))

        assert status == 403 and messages == []

    @pytest.mark.parametrize("platform, contract_class", META)
    def test_an_ignored_delivery(self, monkeypatch, platform, contract_class):
        spec = contract_class()
        _configure(monkeypatch, spec.ENV)
        adapter = spec.make_inbound()

        status, _, messages = _assert_parity(adapter, "POST", adapter.webhook_path, _from_fake_request(spec.ignorable_delivery()))

        assert status == 200 and messages == []

    @pytest.mark.parametrize("platform, contract_class", META)
    def test_the_handshake(self, monkeypatch, platform, contract_class):
        spec = contract_class()
        _configure(monkeypatch, spec.ENV)
        adapter = spec.make_inbound()
        query = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"}

        status, content, _ = _assert_parity(adapter, "GET", adapter.challenge_path, (b"", {}, query))

        assert status == 200 and json.loads(content) == 12345

    @pytest.mark.parametrize("platform, contract_class", META)
    def test_the_handshake_with_a_wrong_token(self, monkeypatch, platform, contract_class):
        spec = contract_class()
        _configure(monkeypatch, spec.ENV)
        adapter = spec.make_inbound()
        query = {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"}

        status, _, _ = _assert_parity(adapter, "GET", adapter.challenge_path, (b"", {}, query))

        assert status == 403


class TestTelegramParity:
    @pytest.fixture
    def spec(self, monkeypatch):
        spec = contract.TestTelegramContract()
        _configure(monkeypatch, spec.ENV)
        return spec

    def test_a_valid_delivery(self, spec):
        adapter = spec.make_inbound()
        status, _, messages = _assert_parity(adapter, "POST", adapter.webhook_path, _from_fake_request(spec.valid_delivery()))

        assert status == 200 and len(messages) == 1

    def test_an_unauthentic_delivery(self, spec):
        adapter = spec.make_inbound()
        status, _, messages = _assert_parity(adapter, "POST", adapter.webhook_path, _from_fake_request(spec.unauthentic_delivery()))

        assert status == 403 and messages == []

    def test_an_ignored_delivery(self, spec):
        adapter = spec.make_inbound()
        status, _, messages = _assert_parity(adapter, "POST", adapter.webhook_path, _from_fake_request(spec.ignorable_delivery()))

        assert status == 200 and messages == []


class TestSlackParity:
    @pytest.fixture
    def adapter(self, monkeypatch):
        from slack_sdk.web.async_client import AsyncWebClient

        from agentkernel.integration.slack.adapter import SlackInboundAdapter

        _configure(monkeypatch, {"SLACK_BOT_TOKEN": "xoxb-test-token", "SLACK_SIGNING_SECRET": SLACK_SIGNING_SECRET})

        class _AuthTestResponse(dict):
            headers = {"x-oauth-scopes": "chat:write"}

        async def _auth_test(self, **kwargs):
            return _AuthTestResponse(ok=True, bot_id=BOT_ID, user_id=BOT_ID, team_id="T1", url="https://test.slack.com/")

        monkeypatch.setattr(AsyncWebClient, "auth_test", _auth_test)
        adapter = SlackInboundAdapter()
        adapter._bot_id = BOT_ID
        return adapter

    @staticmethod
    def _signed(body: dict) -> Delivery:
        payload = json.dumps(body)
        timestamp = str(int(time.time()))
        signature = "v0=" + hmac.new(SLACK_SIGNING_SECRET.encode(), f"v0:{timestamp}:{payload}".encode(), hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature}
        return payload.encode(), headers, None

    def test_a_valid_message_event(self, adapter):
        event = {"type": "message", "channel_type": "channel", "user": "U123", "text": f"hello <@{BOT_ID}>", "channel": "C9", "ts": "111.222"}

        status, _, messages = _assert_parity(
            adapter, "POST", adapter.webhook_path, self._signed({"type": "event_callback", "team_id": "T1", "event": event})
        )

        assert status == 200 and len(messages) == 1

    def test_an_unsigned_delivery(self, adapter):
        delivery = (json.dumps({"type": "event_callback"}).encode(), {"Content-Type": "application/json"}, None)

        status, content, messages = _assert_parity(adapter, "POST", adapter.webhook_path, delivery)

        assert status == 401 and json.loads(content) == {"error": "invalid request"}
        assert messages == []

    def test_the_url_verification_handshake(self, adapter):
        status, content, _ = _assert_parity(adapter, "POST", adapter.webhook_path, self._signed({"type": "url_verification", "challenge": "abc123"}))

        assert status == 200 and b"abc123" in content


class TestTeamsParity:
    @pytest.fixture
    def spec(self, monkeypatch):
        spec = contract.TestTeamsContract()
        _configure(monkeypatch, spec.ENV)
        return spec

    @staticmethod
    def _adapter(spec, process_activity) -> InboundAdapter:
        adapter = spec.make_inbound()
        adapter._adapter = MagicMock()
        adapter._adapter.process_activity = process_activity
        return adapter

    @staticmethod
    def _delivery() -> Delivery:
        body = {"type": "message", "id": "act-1", "text": "hello", "conversation": {"id": "conv-1"}}
        return json.dumps(body).encode(), {"Content-Type": "application/json", "Authorization": "Bearer bot-framework-jwt"}, None

    def test_a_valid_activity(self, spec):
        async def _process(activity, auth_header, logic) -> Any:
            await logic(spec._turn_context())
            return None

        adapter = self._adapter(spec, _process)
        status, _, messages = _assert_parity(adapter, "POST", adapter.webhook_path, self._delivery())

        assert status == 200 and len(messages) == 1

    def test_an_unauthentic_activity(self, spec):
        adapter = self._adapter(spec, AsyncMock(side_effect=PermissionError("bad token")))

        status, content, messages = _assert_parity(adapter, "POST", adapter.webhook_path, self._delivery())

        assert status == 401 and json.loads(content) == {"detail": "Unauthorized"}
        assert messages == []
