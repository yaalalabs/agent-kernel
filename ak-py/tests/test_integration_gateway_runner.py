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


def test_start_registers_the_outbound_adapter_and_runs_it():
    adapter = FakeGatewayAdapter()
    GatewayRunner(adapter).start()

    assert adapter.started is True
    # The registration is what lets the Response Handler resolve this live connection by name.
    assert IntegrationAdapterFactory.create_outbound("fakegateway") is adapter
