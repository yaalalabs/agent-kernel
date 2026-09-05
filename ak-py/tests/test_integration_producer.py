"""IntegrationProducer: what a parsed platform message looks like on the input queue."""

import json

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentRequestAttachmentRef, AgentRequestText
from agentkernel.integration.adapter.base import InboundRequest
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.pipeline.envelope import ATTR_INTEGRATION, ATTR_REQUEST_ID, ATTR_USER_ID, QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    InMemoryTransport.reset()
    yield
    InMemoryTransport.reset()
    AKConfig._reset()


def _request(**overrides) -> InboundRequest:
    defaults = dict(
        session_id="C9:111.222",
        request_id="slack:C9:111.222",
        requests=[AgentRequestText(prompt="hello"), AgentRequestAttachmentRef(attachment_id="att-1")],
        prompt="hello",
        agent="helper",
        user_id="U123",
        group_id="C9",
        reply_context={"channel": "C9", "thread_ts": "111.222"},
    )
    return InboundRequest(**{**defaults, **overrides})


def _enqueue(request: InboundRequest, name: str = "slack"):
    transport = InMemoryTransport()
    IntegrationProducer(transport).enqueue(name, request)
    [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)
    return message


def test_the_routing_attribute_carries_the_adapter_name():
    assert _enqueue(_request()).attributes[ATTR_INTEGRATION] == "slack"


def test_the_reply_context_is_stamped_with_the_reserved_prefix():
    attributes = _enqueue(_request()).attributes
    assert attributes["reply_channel"] == "C9"
    assert attributes["reply_thread_ts"] == "111.222"


def test_the_user_id_stays_in_the_body():
    # ATTR_USER_ID is the WebSocket-entered marker the runner and Response Handler branch on;
    # integration traffic is neither, so it must not be stamped.
    message = _enqueue(_request())
    assert ATTR_USER_ID not in message.attributes
    assert json.loads(message.body)["user_id"] == "U123"


def test_the_platform_ids_become_the_ordering_and_dedup_keys():
    message = _enqueue(_request())
    assert message.group_id == "C9:111.222"
    assert message.dedup_id == "slack:C9:111.222"
    assert message.attributes[ATTR_REQUEST_ID] == "slack:C9:111.222"


def test_a_platform_retry_dedupes_instead_of_running_twice():
    transport = InMemoryTransport()
    producer = IntegrationProducer(transport)
    producer.enqueue("slack", _request())
    producer.enqueue("slack", _request())
    consumer = transport.create_consumer(QueueName.INPUT)
    [message] = consumer.fetch(10, 1.0)
    consumer.ack(message)
    assert consumer.fetch(10, 0.05) == []


def test_the_prebuilt_request_list_travels_in_the_body():
    body = json.loads(_enqueue(_request()).body)
    assert [r["type"] for r in body["requests"]] == ["text", "attachment_ref"]
    assert body["requests"][1]["attachment_id"] == "att-1"
    assert body["prompt"] == "hello"
    assert body["agent"] == "helper"


def test_an_oversized_reply_context_is_rejected_naming_the_adapter():
    oversized = _request(reply_context={"conversation_reference": "x" * (IntegrationProducer.REPLY_CONTEXT_BUDGET_BYTES + 1)})
    with pytest.raises(ValueError) as excinfo:
        _enqueue(oversized, name="teams")
    message = str(excinfo.value)
    assert "teams" in message
    assert str(IntegrationProducer.REPLY_CONTEXT_BUDGET_BYTES) in message


def test_a_realistic_teams_context_fits_the_budget():
    # The largest context of the seven: a serialized ConversationReference.
    reference = json.dumps(
        {"bot": {"id": "b" * 60}, "conversation": {"id": "c" * 200, "tenantId": "t" * 36}, "serviceUrl": "https://smba/" + "s" * 60}
    )
    _enqueue(_request(reply_context={"conversation_reference": reference}), name="teams")
