"""Reusable conformance suite for messaging-integration adapters.

Mirrors ``pipeline/testing.py``'s ``QueueTransportContract``: subclass
:class:`IntegrationAdapterContract` in a test file, implement the hooks, and pytest collects the
contract tests against that adapter pair. The contract asserts the properties every adapter must
hold for the queue hop to work — stable identifiers, an ignorable delivery that is not an error,
a reply context that survives the queue as flat strings inside its budget — leaving each
platform's own parsing and formatting to its per-platform tests.
"""

from typing import Any, Optional

import pytest

from ...pipeline.envelope import ATTR_INTEGRATION, ATTR_REQUEST_ID, REPLY_CONTEXT_PREFIX, QueueName
from ...pipeline.transport.in_memory import InMemoryTransport
from .base import InboundAdapter, InboundParseResult, OutboundAdapter, Source
from .factory import IntegrationAdapterFactory
from .producer import IntegrationProducer


class IntegrationAdapterContract:
    """Adapter conformance tests. Subclass per platform and implement the hooks below."""

    # -- hooks ---------------------------------------------------------------------------

    def make_inbound(self) -> InboundAdapter:
        """The inbound adapter under test."""
        raise NotImplementedError

    def make_outbound(self) -> OutboundAdapter:
        """The outbound adapter under test."""
        raise NotImplementedError

    def valid_delivery(self) -> Any:
        """A raw delivery that parses into exactly one request."""
        raise NotImplementedError

    @property
    def expected_session_id(self) -> str:
        """The session id ``valid_delivery`` must resolve to."""
        raise NotImplementedError

    @property
    def expected_request_id(self) -> str:
        """The request id ``valid_delivery`` must resolve to."""
        raise NotImplementedError

    def ignorable_delivery(self) -> Optional[Any]:
        """A raw delivery the adapter legitimately ignores, or None if it has none."""
        return None

    def unauthentic_delivery(self) -> Optional[Any]:
        """A raw delivery whose verification must fail, or None if the adapter cannot verify."""
        return None

    #: Status the platform expects when verification fails.
    verify_rejection_status: int = 403

    # -- helpers -------------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def _reset_transport(self):
        InMemoryTransport.reset()
        IntegrationAdapterFactory.reset()
        yield
        InMemoryTransport.reset()
        IntegrationAdapterFactory.reset()

    async def _parse_valid(self) -> InboundParseResult:
        adapter = self.make_inbound()
        raw = self.valid_delivery()
        await adapter.verify(raw)
        return await adapter.parse(raw)

    # -- contract ------------------------------------------------------------------------

    def test_declares_its_name_and_source(self):
        inbound, outbound = self.make_inbound(), self.make_outbound()
        assert inbound.name, "an inbound adapter must declare a name: it is the routing attribute"
        assert outbound.name == inbound.name, "the pair must share a name so replies route back"
        assert inbound.source in (Source.WEBHOOK, Source.POLLER)
        if inbound.source == Source.WEBHOOK:
            assert inbound.webhook_path, "a webhook adapter must declare the route the host mounts"

    def test_outbound_resolves_by_name(self):
        resolved = IntegrationAdapterFactory.create_outbound(self.make_inbound().name)
        assert isinstance(resolved, OutboundAdapter)
        assert resolved.name == self.make_inbound().name

    @pytest.mark.asyncio
    async def test_parse_resolves_the_platform_identifiers(self):
        [request] = (await self._parse_valid()).requests
        assert request.session_id == self.expected_session_id
        assert request.request_id == self.expected_request_id

    @pytest.mark.asyncio
    async def test_parse_produces_a_runnable_request_list(self):
        [request] = (await self._parse_valid()).requests
        # ChatService rejects an empty prebuilt list: there would be nothing for the agent to read.
        assert request.requests, "parse must produce at least one AgentRequest"

    @pytest.mark.asyncio
    async def test_reply_context_is_flat_and_stringly_typed(self):
        [request] = (await self._parse_valid()).requests
        assert request.reply_context, "an adapter with no reply context cannot deliver its reply"
        for key, value in request.reply_context.items():
            assert isinstance(key, str) and isinstance(value, str), f"reply_context[{key!r}] must be a string: message attributes are strings"

    @pytest.mark.asyncio
    async def test_reply_context_fits_the_budget(self):
        [request] = (await self._parse_valid()).requests
        # Raises with the adapter named if it does not.
        IntegrationProducer._reply_attributes(self.make_inbound().name, request.reply_context)

    @pytest.mark.asyncio
    async def test_an_ignorable_delivery_is_not_an_error(self):
        raw = self.ignorable_delivery()
        if raw is None:
            pytest.skip("adapter declares no ignorable delivery")
        adapter = self.make_inbound()
        await adapter.verify(raw)
        assert (await adapter.parse(raw)).requests == []

    @pytest.mark.asyncio
    async def test_verify_rejects_an_unauthentic_delivery(self):
        raw = self.unauthentic_delivery()
        if raw is None:
            pytest.skip("adapter verifies inside its SDK dispatch, or has nothing to verify")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            await self.make_inbound().verify(raw)
        assert excinfo.value.status_code == self.verify_rejection_status

    @pytest.mark.asyncio
    async def test_the_queue_hop_preserves_the_reply_context(self):
        adapter = self.make_inbound()
        [request] = (await self._parse_valid()).requests

        transport = InMemoryTransport()
        IntegrationProducer(transport).enqueue(adapter.name, request)
        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)

        assert message.attributes[ATTR_INTEGRATION] == adapter.name
        assert message.attributes[ATTR_REQUEST_ID] == request.request_id
        assert message.group_id == request.session_id, "group_id is the per-conversation FIFO key"
        assert message.dedup_id == request.request_id, "dedup_id is what makes a platform retry safe"
        delivered = {k.removeprefix(REPLY_CONTEXT_PREFIX): v for k, v in message.attributes.items() if k.startswith(REPLY_CONTEXT_PREFIX)}
        assert delivered == request.reply_context

    def test_split_reply_respects_the_platform_limit(self):
        outbound = self.make_outbound()
        chunks = outbound.split_reply("x" * (outbound.MESSAGE_LIMIT * 2))
        assert chunks, "split_reply must always produce something to send"
        if outbound.MAX_CHUNKS is None or outbound.MAX_CHUNKS >= 2:
            assert len(chunks) >= 2, "a reply over the limit must be split, not truncated silently"
