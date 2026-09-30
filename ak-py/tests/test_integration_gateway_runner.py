"""GatewayRunner: hosting a stateful gateway adapter, and its outbound registration."""

from typing import Dict

import pytest

from agentkernel.core.model import AgentReply
from agentkernel.integration.adapter.base import GatewayAdapter, Source
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.gateway import GatewayRunner


class FakeGatewayAdapter(GatewayAdapter):
    name = "fakegateway"

    def __init__(self):
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        pass

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_factory():
    IntegrationAdapterFactory.reset()
    yield
    IntegrationAdapterFactory.reset()


def test_rejects_a_non_realtime_source():
    class WebhookGateway(FakeGatewayAdapter):
        source = Source.WEBHOOK

    with pytest.raises(ValueError, match="not GatewayRunner"):
        GatewayRunner(WebhookGateway())


def test_adapter_property_is_the_hosted_adapter():
    adapter = FakeGatewayAdapter()
    assert GatewayRunner(adapter).adapter is adapter


def test_start_registers_and_unregisters_the_outbound_adapter():
    adapter = FakeGatewayAdapter()
    was_registered = False

    async def fake_start():
        adapter.started = True
        nonlocal was_registered
        # Check if it's registered WHILE running
        was_registered = (IntegrationAdapterFactory.create_outbound("fakegateway") is adapter)

    adapter.start = fake_start
    GatewayRunner(adapter).start()

    assert adapter.started is True
    assert was_registered is True
    # Verify it cleans up properly after the blocking loop exits
    from agentkernel.core.util.factory import AKConfigError
    with pytest.raises(AKConfigError):
        IntegrationAdapterFactory.create_outbound("fakegateway")
