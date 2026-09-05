import logging
from typing import Any, Dict, Optional

from ...core.model import BaseRunRequest
from ...pipeline.envelope import ATTR_INTEGRATION, REPLY_CONTEXT_PREFIX
from ...pipeline.producer import RequestProducer
from ...pipeline.transport.base import QueueTransport
from .base import InboundRequest


class IntegrationProducer:
    """Sends a parsed platform message to the pipeline's input queue (spec #524 §1).

    Wraps the shared :class:`~agentkernel.pipeline.producer.RequestProducer` with the two things
    that are specific to integration traffic: the ``integration`` routing attribute, and the
    ``reply_``-prefixed reply context that tells the Response Handler where the answer goes.
    """
    REPLY_CONTEXT_BUDGET_BYTES = 8192

    _log = logging.getLogger("ak.integration.producer")

    def __init__(self, transport: Optional[QueueTransport] = None):
        """
        :param transport: Transport to send on; defaults to the configured one.
        """
        self._producer = RequestProducer(transport)

    def enqueue(self, adapter_name: str, request: InboundRequest) -> Dict[str, Any]:
        """Enqueue one parsed platform message.

        ``user_id`` is deliberately not stamped as a message attribute: that attribute is the
        WebSocket-entered marker the runner and Response Handler branch on, and integration
        traffic is neither. The user id travels in the body instead.

        :param adapter_name: The inbound adapter's ``name``; becomes the routing attribute.
        :param request: The normalized request to send.
        :return: The transport's send response.
        :raises ValueError: If the serialized reply context exceeds the budget.
        """
        attributes = {ATTR_INTEGRATION: adapter_name, **self._reply_attributes(adapter_name, request.reply_context)}
        body = BaseRunRequest(
            prompt=request.prompt,
            agent=request.agent,
            session_id=request.session_id,
            user_id=request.user_id,
            group_id=request.group_id,
            requests=request.requests,
        )
        result = self._producer.enqueue(
            body,
            request_id=request.request_id,
            attributes=attributes,
            group_id=request.session_id,
            dedup_id=request.request_id,
        )
        self._log.info(f"[ENQUEUED] integration={adapter_name}, session_id={request.session_id}, request_id={request.request_id}")
        return result

    @classmethod
    def _reply_attributes(cls, adapter_name: str, reply_context: Dict[str, str]) -> Dict[str, str]:
        """Prefix the reply context and check it against the budget."""
        attributes = {f"{REPLY_CONTEXT_PREFIX}{key}": value for key, value in reply_context.items()}
        size = sum(len(key.encode()) + len(value.encode()) for key, value in attributes.items())
        if size > cls.REPLY_CONTEXT_BUDGET_BYTES:
            raise ValueError(f"reply_context for integration '{adapter_name}' is {size} bytes, over the {cls.REPLY_CONTEXT_BUDGET_BYTES}-byte budget")
        return attributes
