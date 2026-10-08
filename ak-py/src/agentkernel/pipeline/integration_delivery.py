import logging
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional

from ..core.model import AgentReplyText
from ..core.util.async_bridge import run_async_sync
from .envelope import ATTR_INTEGRATION, ATTR_REQUEST_ID, REPLY_CONTEXT_PREFIX

if TYPE_CHECKING:  # pragma: no cover: annotation only; the adapter package is imported lazily
    from ..integration.adapter.base import OutboundAdapter


class IntegrationDelivery:
    """Integration traffic's return address, and delivery of a reply back to its platform (#524 §6, #760).

    One definition shared by every host that consumes the output queue: the pipeline's
    ResponseHandler and the serverless (Lambda) consumers. Both used to carry their own copy of
    this logic, and the copies drifted (#760).

    It speaks plain attribute mappings rather than ``QueueMessage``, because Lambda hands its
    consumers raw SQS records. It holds no per-message state: one instance serves every consumer
    thread, and the adapters it resolves are cached and shared by the factory.
    """

    def __init__(self, logger: logging.Logger) -> None:
        """
        :param logger: The caller's logger, so delivery log lines keep the caller's logger name.
        """
        self._log = logger

    # -- return address --------------------------------------------------------------------

    @staticmethod
    def integration_of(attributes: Mapping[str, Any]) -> Optional[str]:
        """The adapter name when this is integration traffic, else None.

        Only a non-empty ``str`` counts: a mocked attribute map hands back truthy objects, which
        must not route a message to a platform.

        :param attributes: A message's attributes.
        :return: The value of the ``integration`` attribute, or None.
        """
        integration = attributes.get(ATTR_INTEGRATION)
        return integration if isinstance(integration, str) and integration else None

    @staticmethod
    def is_routing_attribute(name: str) -> bool:
        """Whether an attribute is part of the return address: ``integration`` and every ``reply_*``."""
        return name == ATTR_INTEGRATION or name.startswith(REPLY_CONTEXT_PREFIX)

    @classmethod
    def routing_attributes(cls, attributes: Mapping[str, Any]) -> Dict[str, str]:
        """The return-address subset of an input message's attributes.

        :param attributes: The input message's attributes.
        :return: ``integration`` and every ``reply_*`` attribute, values as ``str``; ``{}`` for
            non-integration traffic.
        """
        return {name: str(value) for name, value in attributes.items() if cls.is_routing_attribute(name)}

    @staticmethod
    def reply_context(attributes: Mapping[str, Any]) -> Dict[str, str]:
        """The adapter's reply context: the ``reply_*`` attributes with the prefix removed.

        :param attributes: The output message's attributes.
        :return: What ``OutboundAdapter.deliver()`` reads.
        """
        return {name.removeprefix(REPLY_CONTEXT_PREFIX): value for name, value in attributes.items() if name.startswith(REPLY_CONTEXT_PREFIX)}

    # -- delivery -------------------------------------------------------------------------

    def deliver(self, integration: str, attributes: Mapping[str, Any], body: Any, status_code: int, session_id: Optional[str] = None) -> None:
        """Deliver one reply back to the messaging platform it came from.

        A status of 400 or above sends the adapter's generic ``ERROR_MESSAGE``, never the internal
        error, which goes to the log instead. Nothing is caught: raising is how both hosts get
        their retries, so a briefly unreachable platform API is retried and then handed to the
        host's permanent-failure path.

        :param integration: The adapter name from the ``integration`` attribute.
        :param attributes: The output message's attributes, carrying the ``reply_*`` context.
        :param body: The decoded output body. ``None`` is treated as ``{}``, and a non-dict body
            as ``{"result": body}``.
        :param status_code: The run's status, already parsed by the caller.
        :param session_id: The session, for logging only.
        :raises AKConfigError: If the name resolves to no adapter.
        :raises ImportError: If the adapter's platform extra is not installed.
        """
        adapter = self._outbound_adapter(integration)
        reply_context = self.reply_context(attributes)
        request_id = attributes.get(ATTR_REQUEST_ID)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            body = {"result": body}

        if status_code >= 400:
            self._log.error(
                f"[OUTPUT ERROR] integration={integration}, session_id={session_id}, "
                f"request_id={request_id}, status_code={status_code}, error={body.get('error')}"
            )
            run_async_sync(adapter.deliver_error(adapter.ERROR_MESSAGE, reply_context))
            return
        run_async_sync(adapter.deliver(AgentReplyText(response=str(body.get("result", ""))), reply_context))
        self._log.info(f"[OUTPUT DONE] Delivered to {integration}: session_id={session_id}, request_id={request_id}")

    def deliver_permanent_failure(self, integration: str, attributes: Mapping[str, Any], session_id: Optional[str] = None) -> None:
        """Tell the platform user that their message failed for good.

        :param integration: The adapter name from the ``integration`` attribute.
        :param attributes: The failed message's attributes, carrying the ``reply_*`` context.
        :param session_id: The session, for logging only.
        :raises Exception: Whatever resolving the adapter or delivering raises; both callers wrap
            permanent-failure handling in a catch-all.
        """
        adapter = self._outbound_adapter(integration)
        run_async_sync(adapter.deliver_error(adapter.ERROR_MESSAGE, self.reply_context(attributes)))
        self._log.info(f"Delivered permanent-failure message to {integration}: session_id={session_id}")

    @staticmethod
    def _outbound_adapter(integration: str) -> "OutboundAdapter":
        """Resolve the outbound adapter named by a message's ``integration`` attribute.

        Imported lazily and locally: messaging platforms are an ``integration`` capability, and
        importing that package at module scope would make every process that consumes the output
        queue (including a Lambda that never sees integration traffic) pay for its SDKs.

        :param integration: The adapter name stamped by the producer.
        :return: The outbound adapter for that name.
        :raises AKConfigError: If the name resolves to no adapter, so the message is retried and
            then permanently failed rather than silently disappearing.
        """
        from ..integration.adapter.factory import IntegrationAdapterFactory

        return IntegrationAdapterFactory.create_outbound(integration)
