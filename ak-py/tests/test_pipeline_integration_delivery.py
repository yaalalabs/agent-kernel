"""IntegrationDelivery: an integration message's return address, and delivery back to its platform (#760)."""

import logging
import sys

import pytest

from agentkernel.core.model import AgentReplyText
from agentkernel.core.util.factory import AKConfigError
from agentkernel.integration.adapter.base import OutboundAdapter
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.pipeline.integration_delivery import IntegrationDelivery

ADAPTER_NAME = "byo_pkg.RecordingOutboundAdapter"
_log = logging.getLogger("ak.test.integration_delivery")


class _RecordingOutboundAdapter(OutboundAdapter):
    """Records what IntegrationDelivery asked it to send."""

    name = ADAPTER_NAME

    def __init__(self):
        self.delivered = []
        self.errors = []
        self.fail_with = None

    async def deliver(self, reply, reply_context):
        if self.fail_with:
            raise self.fail_with
        self.delivered.append((reply, dict(reply_context)))

    async def deliver_error(self, message, reply_context):
        self.errors.append((message, dict(reply_context)))


@pytest.fixture
def adapter():
    fake = _RecordingOutboundAdapter()
    IntegrationAdapterFactory.reset()
    IntegrationAdapterFactory._cache[ADAPTER_NAME] = fake
    yield fake
    IntegrationAdapterFactory.reset()


def _attrs(**extra):
    return {"request_id": "r1", "integration": ADAPTER_NAME, "reply_channel": "C9", "reply_thread_ts": "111.222", **extra}


def test_integration_of():
    assert IntegrationDelivery.integration_of({"integration": "slack"}) == "slack"
    assert IntegrationDelivery.integration_of({}) is None
    assert IntegrationDelivery.integration_of({"integration": ""}) is None
    # A MagicMock-backed attribute map hands back truthy non-str values: they must not count.
    assert IntegrationDelivery.integration_of({"integration": object()}) is None
    assert IntegrationDelivery.integration_of({"integration": 1}) is None


def test_routing_attributes_pick_integration_and_reply_prefix_only():
    attributes = {
        "request_id": "r1",
        "user_id": "u1",
        "status_code": "200",
        "endpoint_url": "https://ws.example",
        "integration": "slack",
        "reply_channel": "C9",
        "reply_ack_ts": 123,
    }

    assert IntegrationDelivery.routing_attributes(attributes) == {"integration": "slack", "reply_channel": "C9", "reply_ack_ts": "123"}
    assert IntegrationDelivery.routing_attributes({"request_id": "r1", "status_code": "200"}) == {}
    assert IntegrationDelivery.is_routing_attribute("integration")
    assert IntegrationDelivery.is_routing_attribute("reply_thread_ts")
    assert not IntegrationDelivery.is_routing_attribute("request_id")
    assert not IntegrationDelivery.is_routing_attribute("endpoint_url")


def test_reply_context_strips_the_prefix():
    assert IntegrationDelivery.reply_context({"reply_channel": "C9", "integration": "slack", "request_id": "r1"}) == {"channel": "C9"}


def test_deliver_sends_the_result_text(adapter):
    IntegrationDelivery(_log).deliver(ADAPTER_NAME, _attrs(), {"result": "hi", "session_id": "s1"}, 200, session_id="s1")

    [(reply, context)] = adapter.delivered
    assert reply == AgentReplyText(response="hi")
    assert context == {"channel": "C9", "thread_ts": "111.222"}
    assert adapter.errors == []


@pytest.mark.parametrize("status_code", [400, 500])
def test_deliver_on_error_status_sends_the_generic_message(adapter, caplog, status_code):
    with caplog.at_level(logging.ERROR, logger=_log.name):
        IntegrationDelivery(_log).deliver(ADAPTER_NAME, _attrs(), {"error": "internal stack trace"}, status_code, session_id="s1")

    assert adapter.errors == [(_RecordingOutboundAdapter.ERROR_MESSAGE, {"channel": "C9", "thread_ts": "111.222"})]
    assert adapter.delivered == []
    assert "internal stack trace" in caplog.text
    assert f"status_code={status_code}" in caplog.text
    assert all("internal stack trace" not in message for message, _ in adapter.errors)


def test_non_dict_and_missing_bodies(adapter):
    delivery = IntegrationDelivery(_log)
    delivery.deliver(ADAPTER_NAME, _attrs(), "plain", 200)
    delivery.deliver(ADAPTER_NAME, _attrs(), None, 200)

    assert [reply.response for reply, _ in adapter.delivered] == ["plain", ""]


def test_delivery_failure_propagates(adapter):
    adapter.fail_with = ConnectionError("platform down")

    with pytest.raises(ConnectionError, match="platform down"):
        IntegrationDelivery(_log).deliver(ADAPTER_NAME, _attrs(), {"result": "hi"}, 200)


def test_deliver_permanent_failure(adapter):
    IntegrationDelivery(_log).deliver_permanent_failure(ADAPTER_NAME, _attrs(), session_id="s1")

    assert adapter.errors == [(_RecordingOutboundAdapter.ERROR_MESSAGE, {"channel": "C9", "thread_ts": "111.222"})]


def test_unresolvable_adapter_raises():
    IntegrationAdapterFactory.reset()

    with pytest.raises(AKConfigError):
        IntegrationDelivery(_log).deliver("carrier-pigeon", {"integration": "carrier-pigeon"}, {"result": "hi"}, 200)


def test_module_does_not_import_integration():
    saved_modules = {name: module for name, module in sys.modules.items() if name == "agentkernel" or name.startswith("agentkernel.")}
    for name in saved_modules:
        del sys.modules[name]

    try:
        import agentkernel.pipeline.integration_delivery  # noqa: F401

        assert not [name for name in sys.modules if name.startswith("agentkernel.integration")]
    finally:
        for name in list(sys.modules):
            if name == "agentkernel" or name.startswith("agentkernel."):
                del sys.modules[name]
        sys.modules.update(saved_modules)
