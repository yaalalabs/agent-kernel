import json
from typing import Any, Dict, Optional

from ..core.model import BaseRunRequest
from .envelope import ATTR_REQUEST_ID, QueueMessage, QueueName
from .transport.base import QueueTransport, QueueTransportFactory


class RequestProducer:
    """Public input-queue producer: the enqueue seam shared by every edge (spec #524 §3).

    Extracted from ``RestHandler._enqueue_request``, which was private, minted its own request
    id, and took no extra attributes: a messaging edge needs to supply the platform's own message
    id (so a webhook retry deduplicates against it) and to stamp its routing/reply attributes.
    """

    def __init__(self, transport: Optional[QueueTransport] = None):
        """
        :param transport: Transport to send on; defaults to the configured one. Callers that own
            a transport (the REST handler's ``get_transport()`` seam) pass theirs.
        """
        self._transport = transport or QueueTransportFactory.create()

    def enqueue(
        self,
        body: BaseRunRequest,
        request_id: str,
        attributes: Optional[Dict[str, str]] = None,
        group_id: Optional[str] = None,
        dedup_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the input-queue envelope for a chat request and send it.

        ``exclude_none`` keeps the body JSON identical to the pre-#495 SQS path (which dumped
        the validated body model with ``exclude_none=True``).

        :param body: The validated chat request.
        :param request_id: Stamped as ATTR_REQUEST_ID and used as the default dedup id.
        :param attributes: Extra message attributes merged over the request id.
        :param group_id: FIFO ordering key; defaults to the body's session_id.
        :param dedup_id: Publish-time deduplication key; defaults to ``request_id``.
        :return: The transport's send response, or an empty dict when it returns none.
        """
        message = QueueMessage(
            body=json.dumps(body.model_dump(exclude_none=True)),
            attributes={ATTR_REQUEST_ID: request_id, **(attributes or {})},
            group_id=group_id or body.session_id,
            dedup_id=dedup_id or request_id,
        )
        return self._transport.send(QueueName.INPUT, message) or {}
