"""
Messaging and realtime principals (spec `docs/specs/603-identity-rbac-registry/` 8.4, iteration 9).

The edge builds the principal: `IntegrationProducer.enqueue` turns the adapter's sender id,
namespace and claims into a `messaging:<platform>` principal (or `realtime:<gateway>` for a
stateful edge) on the queued body, and a delivery with no sender runs anonymous. The runner stays
platform-agnostic: it reads a principal like any other. Each adapter's namespace is pinned in its
own suite; here is the seam they all pass through.
"""

import json

import pytest

from agentkernel.core.model import AgentRequestText
from agentkernel.integration.adapter.base import InboundRequest, Source, StatefulEdgeAdapter
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.pipeline.envelope import ATTR_USER_ID, QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    from agentkernel.core.config import AKConfig

    AKConfig._reset()
    InMemoryTransport.reset()
    yield
    InMemoryTransport.reset()
    AKConfig._reset()


def _inbound(**overrides) -> InboundRequest:
    fields = {"session_id": "s1", "request_id": "r1", "requests": [AgentRequestText(prompt="hi")], "prompt": "hi"}
    fields.update(overrides)
    return InboundRequest(**fields)


def _enqueue(request: InboundRequest, adapter_name: str = "slack", **kwargs) -> dict:
    transport = InMemoryTransport()
    message = None
    IntegrationProducer(transport).enqueue(adapter_name, request, **kwargs)
    [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)
    return {"attributes": message.attributes, "body": json.loads(message.body)}


class TestProducerPrincipal:
    def test_a_sender_becomes_a_messaging_principal_with_its_platform_scope(self):
        sent = _enqueue(_inbound(user_id="U123", namespace="T1", claims={"authentication_results": "spf=pass"}), "slack")

        principal = sent["body"]["principal"]
        assert (principal["subject"], principal["provider"], principal["namespace"]) == ("U123", "messaging:slack", "T1")
        assert principal["claims"] == {"authentication_results": "spf=pass"}
        assert (principal["kind"], principal["groups"], principal["roles"]) == ("user", [], [])
        assert "user_id" not in sent["body"]

    def test_a_realtime_edge_gets_the_realtime_prefix(self):
        sent = _enqueue(_inbound(user_id="human", namespace="lk-key"), "livekit", source=Source.REALTIME)

        principal = sent["body"]["principal"]
        assert (principal["subject"], principal["provider"], principal["namespace"]) == ("human", "realtime:livekit", "lk-key")

    def test_a_delivery_without_a_sender_runs_anonymous(self):
        sent = _enqueue(_inbound(user_id=None), "gmail")

        assert "principal" not in sent["body"]

    def test_the_sender_is_still_not_the_websocket_marker(self):
        """ATTR_USER_ID is the WebSocket-entered marker the runners branch on; integration traffic never stamps it."""
        sent = _enqueue(_inbound(user_id="U123", namespace="T1"), "slack")

        assert ATTR_USER_ID not in sent["attributes"]


class _Edge(StatefulEdgeAdapter):
    name = "edge"
    session_id = "room-1"

    async def start(self):
        pass

    async def stop(self):
        pass

    async def deliver_chunk(self, chunk, reply_context):
        pass

    async def deliver(self, reply, reply_context):
        pass

    async def deliver_error(self, message, reply_context):
        pass


class TestStatefulEdgeEnqueue:
    def test_the_edge_names_the_participant_and_its_scope(self):
        request = _Edge()._enqueue(AgentRequestText(prompt="hi"), user_id="human", namespace="lk-key")

        assert (request.user_id, request.namespace, request.session_id) == ("human", "lk-key", "room-1")

    def test_without_a_participant_the_request_names_nobody(self):
        request = _Edge()._enqueue(AgentRequestText(prompt="hi"))

        assert (request.user_id, request.namespace) == (None, None)
