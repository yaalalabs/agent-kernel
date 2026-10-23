import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, ClassVar, Mapping, Optional

from pydantic import BaseModel

from ..core.config import AKConfig
from ..core.model import BaseRunRequest
from .envelope import ATTR_PROTOCOL
from .producer import RequestProducer
from .response_store.base import ResponseStore
from .response_store.factory import ResponseStoreFactory
from .transport.base import QueueTransport, QueueTransportFactory

if TYPE_CHECKING:  # pragma: no cover: annotation only
    from ..core.config import _ResponseStoreConfig


class QueuedReply(BaseModel):
    """One whole reply read back from the response store.

    ``body`` is kept exactly as the Agent Runner produced it (``ResponseBuilder.build_response``),
    so a caller reads the same keys a REST client does; the properties only save each surface
    from repeating the dict checks.
    """

    request_id: str
    status_code: int = 200
    body: Any = None

    @property
    def is_error(self) -> bool:
        """Whether the run failed: a status of 400 or above."""
        return self.status_code >= 400

    @property
    def result(self) -> Any:
        """The reply's ``result`` when the body is a dict, else None."""
        return self.body.get("result") if isinstance(self.body, dict) else None

    @property
    def media_type(self) -> Optional[str]:
        """The structured reply's ``media_type`` when the body is a dict and carries one, else None."""
        return self.body.get("media_type") if isinstance(self.body, dict) else None

    @property
    def error(self) -> Optional[str]:
        """The failed run's ``error`` when the body is a dict and carries one, else None."""
        return self.body.get("error") if isinstance(self.body, dict) else None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "QueuedReply":
        """Build a reply from a response-store record (``{session_id, request_id, status_code, body}``).

        A missing status counts as 200, the rule REST applies to records written before the
        status was forwarded.

        :param record: The record the Response Handler stored.
        :return: The reply.
        """
        return cls(
            request_id=str(record.get("request_id") or ""),
            status_code=int(record.get("status_code") or 200),
            body=record.get("body"),
        )


class ReplyTimeoutError(TimeoutError):
    """The wait budget ran out before the reply was stored."""

    def __init__(self, request_id: str, retry_count: int, delay: float):
        """
        :param request_id: The request that got no reply.
        :param retry_count: The number of store reads the budget allowed.
        :param delay: The seconds between those reads.
        """
        super().__init__(f"No reply stored for request_id {request_id} after {retry_count} reads {delay}s apart")
        self.request_id = request_id
        self.retry_count = retry_count
        self.delay = delay


class QueueRequestClient:
    """Puts one chat request on the input queue and waits for its whole reply in the response store.

    The "enqueue, then wait" half of the REST chat route, for surfaces whose caller is waiting on
    one whole reply (A2A and MCP, #780). It talks only to the ``QueueTransport`` and
    ``ResponseStore`` interfaces, so every built-in and bring-your-own backend works unchanged.
    Messages it sends carry the ``protocol`` attribute, which tells the runners and the Response
    Handler to deliver one whole reply to the store whatever ``execution.mode`` is.

    One instance serves every request a surface is handling at once, all on the server's event
    loop: the transport and store are built on that loop before any ``to_thread`` hand-off, and
    both are already shared across worker threads by the REST handler.
    """

    DEFAULT_BUDGET: ClassVar[tuple[int, float]] = (60, 1.0)

    _log = logging.getLogger("ak.pipeline.request_client")

    def __init__(
        self,
        transport: Optional[QueueTransport] = None,
        response_store: Optional[ResponseStore] = None,
        budget: Optional[tuple[int, float]] = None,
    ):
        """
        :param transport: Transport to enqueue on; defaults to the configured one, built on first use.
        :param response_store: Store to read replies from; defaults to the configured one, built on first use.
        :param budget: ``(retry_count, delay)``; defaults to ``budget_for(execution.response_store)``.
            An explicit argument means the configuration is never read for it.
        """
        self._transport = transport
        self._response_store = response_store
        self._budget = budget

    async def request(self, body: BaseRunRequest, protocol: str) -> QueuedReply:
        """Enqueue one chat request tagged with ``protocol`` and wait for its whole reply.

        The group id is the session id, which keeps one conversation's messages in order, and the
        dedup id is the fresh request id (``RequestProducer``'s defaults). A reply with an error
        status is returned, not raised: the caller checks ``is_error``.

        :param body: The chat request; ``session_id`` and ``prompt`` are required.
        :param protocol: The surface's name, stamped as the ``protocol`` attribute.
        :return: The stored reply.
        :raises ValueError: If ``session_id``, ``prompt`` or ``protocol`` is empty; nothing is sent.
        :raises ReplyTimeoutError: If the budget runs out before the reply is stored.
        """
        self._validate(body, protocol)
        transport = self._get_transport()
        store = self._get_store()
        retry_count, delay = self._get_budget()

        request_id = str(uuid.uuid4())
        self._log.info(f"[ENQUEUE] protocol={protocol}, session_id={body.session_id}, request_id={request_id}, agent={body.agent}")
        # Offload the sync send so it doesn't block the event loop.
        await asyncio.to_thread(RequestProducer(transport).enqueue, body, request_id, {ATTR_PROTOCOL: protocol})

        record = await self.wait_for_record(store, request_id, retry_count, delay)
        if record is None:
            raise ReplyTimeoutError(request_id, retry_count, delay)
        reply = QueuedReply.from_record(record)
        self._log.info(f"[REPLY] protocol={protocol}, request_id={request_id}, status_code={reply.status_code}")
        return reply

    @classmethod
    def budget_for(cls, response_store_config: Optional["_ResponseStoreConfig"]) -> tuple[int, float]:
        """The ``(retry_count, delay)`` wait budget every queued surface shares.

        :param response_store_config: The ``execution.response_store`` block, or None when absent.
        :return: ``DEFAULT_BUDGET`` without a block, else the block's ``retry_count`` and ``delay``.
        """
        if response_store_config is None:
            return cls.DEFAULT_BUDGET
        return response_store_config.retry_count, response_store_config.delay

    @staticmethod
    async def wait_for_record(store: ResponseStore, request_id: str, retry_count: int, delay: float) -> Optional[dict]:
        """Read the store until the record for ``request_id`` is there, or the budget is spent.

        The first read happens straight away, and each read deletes the record it returns. Full
        records are read (``get_record``) rather than bodies, so the stored status_code reaches the
        caller on shared stores too. The longest wait is ``(retry_count - 1) * delay``.

        :param store: The response store to read.
        :param request_id: The request whose record to wait for.
        :param retry_count: The number of reads.
        :param delay: The seconds slept between reads (not after the last one).
        :return: The record, or None once the budget is spent.
        """
        for attempt in range(retry_count):
            record = await asyncio.to_thread(store.get_record, request_id, True)
            if record is not None:
                return record
            if attempt < retry_count - 1:
                await asyncio.sleep(delay)
        return None

    @staticmethod
    def protocol_of(attributes: Mapping[str, Any]) -> Optional[str]:
        """The surface name when a caller is waiting on the store for this message, else None.

        Only a non-empty ``str`` counts, the rule ``IntegrationDelivery.integration_of`` applies:
        a mocked attribute map hands back truthy objects, which must not reroute a message.

        :param attributes: A message's attributes.
        :return: The value of the ``protocol`` attribute, or None.
        """
        protocol = attributes.get(ATTR_PROTOCOL)
        return protocol if isinstance(protocol, str) and protocol else None

    # -- internals -------------------------------------------------------------------------

    @staticmethod
    def _validate(body: BaseRunRequest, protocol: str) -> None:
        """Refuse a request the runner could only reject, before anything is sent.

        The session and prompt messages match ``ChatService._validate`` word for word.

        :raises ValueError: If ``session_id``, ``prompt`` or ``protocol`` is empty.
        """
        if not body.session_id:
            raise ValueError("No session_id is provided in the request")
        if not body.prompt:
            raise ValueError("No prompt provided in the request")
        if not protocol:
            raise ValueError("protocol is required")

    def _get_transport(self) -> QueueTransport:
        if self._transport is None:
            self._transport = QueueTransportFactory.create()
        return self._transport

    def _get_store(self) -> ResponseStore:
        if self._response_store is None:
            self._response_store = ResponseStoreFactory.create()
        return self._response_store

    def _get_budget(self) -> tuple[int, float]:
        if self._budget is None:
            self._budget = self.budget_for(AKConfig.get().execution.response_store)
        return self._budget
