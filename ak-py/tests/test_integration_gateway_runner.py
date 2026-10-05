"""GatewayRunner: hosting a stateful gateway adapter, and its outbound registration."""

from typing import Dict

import pytest

from agentkernel.core.model import AgentReply
from agentkernel.integration.adapter.base import Source, StatefulEdgeAdapter
from agentkernel.integration.adapter.gateway import GatewayRunner
from agentkernel.integration.adapter.registry import StatefulEdgeRegistry


class FakeStatefulEdgeAdapter(StatefulEdgeAdapter):
    name = "fakegateway"

    def __init__(self):
        self.started = False
        self.session_id = "test-session-123"

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        pass

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        pass

    async def deliver_chunk(self, chunk, reply_context: Dict[str, str]) -> None:
        pass

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_registry():
    StatefulEdgeRegistry.reset()
    yield
    StatefulEdgeRegistry.reset()


def test_rejects_a_non_realtime_source():
    class WebhookGateway(FakeStatefulEdgeAdapter):
        source = Source.WEBHOOK

    with pytest.raises(ValueError, match="not GatewayRunner"):
        GatewayRunner(WebhookGateway())


def test_adapter_property_is_the_hosted_adapter():
    adapter = FakeStatefulEdgeAdapter()
    assert GatewayRunner(adapter).adapter is adapter


def test_start_registers_and_unregisters_the_outbound_adapter():
    adapter = FakeStatefulEdgeAdapter()
    was_registered = False

    async def fake_start():
        adapter.started = True
        nonlocal was_registered
        # Check if it's registered WHILE running
        was_registered = StatefulEdgeRegistry.get(adapter.session_id) is adapter

    adapter.start = fake_start
    GatewayRunner(adapter).start()

    assert adapter.started is True
    assert was_registered is True
    # Verify it cleans up properly after the blocking loop exits
    assert StatefulEdgeRegistry.get(adapter.session_id) is None
