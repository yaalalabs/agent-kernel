import pytest

from agentkernel.pipeline.testing import QueueTransportContract
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


class TestInMemoryTransportContract(QueueTransportContract):
    """Run the transport contract against the in_memory transport."""

    ack_wait = 0.2

    @pytest.fixture(autouse=True)
    def _reset_transport_state(self):
        InMemoryTransport.reset()
        yield
        InMemoryTransport.reset()

    def make_transport(self) -> InMemoryTransport:
        return InMemoryTransport(ack_wait=self.ack_wait, dedup_window=1.0)
