"""WebhookRESTRequestHandler: the generic host for a push-based inbound adapter."""

import json
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from agentkernel.api.http import RESTAPI
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReply, AgentRequestText
from agentkernel.core.util.factory import AKConfigError
from agentkernel.integration.adapter.base import InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter, Source
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.pipeline.envelope import ATTR_INTEGRATION, QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

ADAPTER_NAME = "byo_pkg.FakeOutboundAdapter"


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


class FakeInboundAdapter(InboundAdapter):
    name = ADAPTER_NAME
    source = Source.WEBHOOK
    webhook_path = "/fake/webhook"

    def __init__(self, requests: Optional[List[InboundRequest]] = None, response: Any = None, secret: Optional[str] = None):
        self._requests = requests if requests is not None else [_inbound()]
        self._response = response
        self._secret = secret

    async def verify(self, raw: Request) -> None:
        if self._secret and raw.headers.get("x-secret") != self._secret:
            raise HTTPException(status_code=403, detail="Invalid secret token")

    async def parse(self, raw: Request) -> InboundParseResult:
        return InboundParseResult(requests=list(self._requests), response=self._response)


class ChallengingInboundAdapter(FakeInboundAdapter):
    challenge_path = "/fake/webhook"

    async def challenge(self, raw: Request) -> Any:
        return int(raw.query_params["hub.challenge"])


def _inbound(**overrides) -> InboundRequest:
    defaults = dict(
        session_id="s1",
        request_id="r1",
        requests=[AgentRequestText(prompt="hi")],
        prompt="hi",
        user_id="u1",
        reply_context={"channel": "C9"},
    )
    return InboundRequest(**{**defaults, **overrides})


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    InMemoryTransport.reset()
    FakeOutboundAdapter.acknowledged = []
    IntegrationAdapterFactory.reset()
    IntegrationAdapterFactory._cache[ADAPTER_NAME] = FakeOutboundAdapter()
    yield
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    AKConfig._reset()


def _client(adapter: InboundAdapter, transport: Optional[InMemoryTransport] = None) -> TestClient:
    handler = WebhookRESTRequestHandler(adapter, producer=IntegrationProducer(transport or InMemoryTransport()))
    app = FastAPI()
    app.include_router(handler.get_router())
    return TestClient(app)


def _drain(transport: InMemoryTransport):
    return transport.create_consumer(QueueName.INPUT).fetch(10, 0.2)


class TestRouting:
    def test_the_adapters_delivery_route_is_mounted(self):
        assert _client(FakeInboundAdapter()).post("/fake/webhook", json={}).status_code == 200

    def test_the_challenge_route_is_mounted_only_when_declared(self):
        assert _client(FakeInboundAdapter()).get("/fake/webhook").status_code == 405
        response = _client(ChallengingInboundAdapter()).get("/fake/webhook", params={"hub.challenge": "12345"})
        assert response.status_code == 200 and response.json() == 12345

    def test_no_health_route_is_added(self):
        # RESTAPI registers /health app-wide before any router; a per-handler copy would be dead code.
        assert [route.path for route in WebhookRESTRequestHandler(FakeInboundAdapter()).get_router().routes] == ["/fake/webhook"]

    def test_a_poller_adapter_cannot_be_mounted_here(self):
        adapter = FakeInboundAdapter()
        adapter.source = Source.POLLER
        with pytest.raises(ValueError, match="PollerRunner"):
            WebhookRESTRequestHandler(adapter)

    def test_an_adapter_without_a_route_is_rejected(self):
        adapter = FakeInboundAdapter()
        adapter.webhook_path = ""
        with pytest.raises(ValueError, match="webhook_path"):
            WebhookRESTRequestHandler(adapter)


class TestDelivery:
    def test_a_parsed_delivery_is_enqueued(self):
        transport = InMemoryTransport()
        assert _client(FakeInboundAdapter(), transport).post("/fake/webhook", json={}).status_code == 200
        [message] = _drain(transport)
        assert message.attributes[ATTR_INTEGRATION] == ADAPTER_NAME
        assert json.loads(message.body)["session_id"] == "s1"

    def test_every_message_in_a_batched_delivery_is_enqueued(self):
        transport = InMemoryTransport()
        batch = [_inbound(session_id="s1", request_id="r1"), _inbound(session_id="s2", request_id="r2")]
        _client(FakeInboundAdapter(requests=batch), transport).post("/fake/webhook", json={})
        assert sorted(m.group_id for m in _drain(transport)) == ["s1", "s2"]

    def test_the_acknowledgement_runs_at_the_edge_and_extends_the_reply_context(self):
        transport = InMemoryTransport()
        _client(FakeInboundAdapter(), transport).post("/fake/webhook", json={})
        assert FakeOutboundAdapter.acknowledged == [{"channel": "C9"}]
        [message] = _drain(transport)
        # The ack's return value must reach the outbound side, or the reply cannot edit it.
        assert message.attributes["reply_ack_ts"] == "ack-1"

    def test_an_ignored_delivery_succeeds_without_enqueueing(self):
        transport = InMemoryTransport()
        response = _client(FakeInboundAdapter(requests=[]), transport).post("/fake/webhook", json={})
        assert response.status_code == 200 and response.json() == {"status": "ok"}
        assert _drain(transport) == []
        assert FakeOutboundAdapter.acknowledged == [], "nothing to acknowledge for an ignored delivery"

    def test_an_sdk_owned_response_is_returned_verbatim(self):
        # Bolt answers Slack's url_verification handshake itself; the host must not overwrite it.
        from fastapi.responses import JSONResponse

        client = _client(FakeInboundAdapter(requests=[], response=JSONResponse({"challenge": "abc"}, status_code=201)))
        response = client.post("/fake/webhook", json={})
        assert response.status_code == 201 and response.json() == {"challenge": "abc"}


class TestRejection:
    def test_verification_failure_rejects_before_enqueueing(self):
        transport = InMemoryTransport()
        client = _client(FakeInboundAdapter(secret="s3cret"), transport)
        assert client.post("/fake/webhook", json={}, headers={"x-secret": "wrong"}).status_code == 403
        assert _drain(transport) == []
        assert FakeOutboundAdapter.acknowledged == []

    def test_a_verified_delivery_passes(self):
        client = _client(FakeInboundAdapter(secret="s3cret"))
        assert client.post("/fake/webhook", json={}, headers={"x-secret": "s3cret"}).status_code == 200

    def test_an_enqueue_failure_surfaces_as_a_5xx_so_the_platform_retries(self):
        class BrokenProducer(IntegrationProducer):
            def enqueue(self, adapter_name, request):
                raise RuntimeError("broker unreachable")

        handler = WebhookRESTRequestHandler(FakeInboundAdapter(), producer=BrokenProducer(InMemoryTransport()))
        app = FastAPI()
        app.include_router(handler.get_router())
        with pytest.raises(RuntimeError):
            # raise_server_exceptions surfaces it here; over the wire FastAPI answers 500.
            TestClient(app).post("/fake/webhook", json={})


class TestPipelineRequirement:
    def test_the_handler_declares_that_it_needs_the_pipeline(self):
        assert WebhookRESTRequestHandler(FakeInboundAdapter()).requires_pipeline is True

    def test_restapi_run_refuses_to_serve_it(self):
        with pytest.raises(AKConfigError) as excinfo:
            RESTAPI.run([WebhookRESTRequestHandler(FakeInboundAdapter())])
        message = str(excinfo.value)
        assert "WebhookRESTRequestHandler" in message
        assert "IOHandler.run" in message
