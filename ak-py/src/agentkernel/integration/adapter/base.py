"""The messaging-integration adapter seam (spec #524 §1).

A platform integration is two pure translation functions with a queue between them:

- :class:`InboundAdapter` turns one platform delivery into normalized
  :class:`InboundRequest` envelopes. It verifies, parses, downloads and stores attachments —
  and never runs the agent.
- :class:`OutboundAdapter` turns an agent reply back into platform API calls, using only the
  flat ``reply_context`` the inbound side resolved.

Between them sits the pipeline's input queue, so a slow agent run can no longer hold a webhook
turn open past the platform's delivery timeout.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ...core.model import AgentReply, AgentRequestUnion

ATTACHMENTS_DISABLED_ERROR = (
    "Attachments from messaging integrations require multimodal support — " "set multimodal.enabled: true in config.yaml to accept images and files"
)
SESSION_CACHE_ERROR = (
    "multimodal.storage_type 'session_cache' is not supported for messaging integrations — "
    "the agent runs in a different process; use in_memory, redis, or dynamodb"
)


class Source(StrEnum):
    """How an inbound adapter is hosted."""

    WEBHOOK = "webhook"
    POLLER = "poller"


class InboundRequest(BaseModel):
    """One normalized platform message, fully resolved at the edge.

    ``session_id`` and ``request_id`` are resolved here rather than downstream because only the
    adapter knows the platform's own identifiers: the session key is the platform's conversation
    key, and the request id is the platform's message id, which is what makes a webhook retry
    deduplicate instead of running the agent twice.
    """

    session_id: str
    request_id: str
    requests: List[AgentRequestUnion]
    prompt: str = ""
    agent: Optional[str] = None
    user_id: Optional[str] = None
    group_id: Optional[str] = None
    reply_context: Dict[str, str] = Field(default_factory=dict)


@dataclass
class InboundParseResult:
    """What one platform delivery parsed into.

    ``requests`` is a list because a single delivery can carry several messages: the Meta
    platforms iterate ``entry`` x ``messaging``/``messages``. An empty list means the delivery
    is legitimately ignored — a bot's own message, a non-message activity, an echo, a delivery
    receipt — so "ignore" never has to be an exception.

    ``response`` carries the platform-expected HTTP response when the platform SDK produced one
    itself (Bolt's ``handle``, which also answers Slack's ``url_verification`` handshake, and
    the Bot Framework adapter's invoke response). ``None`` means the host answers with the
    adapter's :meth:`InboundAdapter.success_response`.
    """

    requests: List[InboundRequest] = field(default_factory=list)
    response: Any = None


class InboundAdapter(ABC):
    """Platform -> Agent Kernel. Verifies and normalizes; never executes.

    An implementation must not import or call ChatService, AgentService or Runtime. Its only
    side effects are platform API calls (attachment downloads) and attachment storage.
    """
    name: str = ""
    source: Source = Source.WEBHOOK
    webhook_path: str = ""
    challenge_path: Optional[str] = None

    async def verify(self, raw: Any) -> None:
        """Reject a delivery that did not come from the platform.

        Concrete and a no-op by default: Slack and Teams verify inside their SDK's own dispatch
        (so their check happens during :meth:`parse`), and a poller has nothing to verify.
        Implementations that do override it raise the platform's expected ``HTTPException``, and
        it always runs before parsing and before anything is enqueued.

        :param raw: The delivery as the host received it.
        """

    @abstractmethod
    async def parse(self, raw: Any) -> InboundParseResult:
        """Normalize one platform delivery into queue-ready requests.

        :param raw: The delivery as the host received it — a FastAPI ``Request`` for a webhook
            adapter, whatever :meth:`PollingInboundAdapter.poll` yielded for a poller.
        :return: The parsed requests (possibly none) and any SDK-produced HTTP response.
        """

    async def challenge(self, raw: Any) -> Any:
        """Answer the platform's subscription handshake.

        :param raw: The incoming request.
        :return: The platform's expected handshake response.
        :raises HTTPException: 404 by default — most platforms have no handshake.
        """
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"{self.name} has no webhook challenge endpoint")

    def success_response(self) -> Any:
        """The success body returned when the platform SDK did not produce a response itself."""
        return {"status": "ok"}


class PollingInboundAdapter(InboundAdapter):
    """An inbound adapter whose events are pulled rather than pushed.

    Hosted by ``PollerRunner`` in its own process, so poller lifetime is never coupled to the
    replica count of the webhook tier.
    """

    source = Source.POLLER
    poll_interval: float = 30.0

    @abstractmethod
    async def poll(self) -> List[Any]:
        """Return the raw events to parse this iteration. Must not run the agent.

        :return: Raw platform events, each of which is passed to :meth:`parse`.
        """

    def mark_handled(self, raw: Any) -> None:
        """Record that a raw event has been enqueued, so the next poll skips it.

        Default no-op: a platform whose poll query stops returning an event once it has been
        acted on needs nothing here.

        :param raw: The event that was just enqueued.
        """


class OutboundAdapter(ABC):
    """Agent Kernel -> platform. Delivers a reply using only the reply context.

    Instances are cached by the factory and shared across the Response Handler's consumer
    threads, so an implementation must keep no per-message state on ``self``. Each call is
    driven on its own event loop, so a client bound to a loop (an ``httpx.AsyncClient`` held on
    ``self``) would break on the second delivery: construct such clients per call.
    """

    name: str = ""
    MESSAGE_LIMIT: int = 4096
    MAX_CHUNKS: Optional[int] = None
    TRUNCATION_NOTICE: str = "The response was truncated because it exceeds this platform's size limit."
    ERROR_MESSAGE: str = "Sorry, there was an error processing your request."

    @abstractmethod
    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        """Send the agent reply to the platform.

        The reply always arrives as an ``AgentReplyText``: the Agent Runner serializes the typed
        reply to its string form before the output queue, which is the same collapse every
        integration performed inline before this seam existed.

        Raising hands the message back to the consumer loop, which retries it up to
        ``execution.queues.output.max_receive_count`` and then calls :meth:`deliver_error`.

        :param reply: The agent's reply.
        :param reply_context: The delivery coordinates resolved at the edge.
        """

    @abstractmethod
    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        """Send a user-facing failure message, so a user is never left silent.

        :param message: The message to show; normally :attr:`ERROR_MESSAGE`.
        :param reply_context: The delivery coordinates resolved at the edge.
        """

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        """Acknowledge receipt at the edge, before the agent runs.

        This is the "thinking" message, the typing indicator, the read receipt — the feedback a
        user expects immediately, which is why it stays at the edge rather than moving to the
        Response Handler.

        :param reply_context: The delivery coordinates resolved so far.
        :return: Extra reply-context entries to merge in (e.g. the id of the acknowledgement
            message, so delivery can edit it). Empty by default.
        """
        return {}

    def split_reply(self, text: str) -> list:
        """Chunk a reply into pieces the platform will accept.

        :param text: The full reply text.
        :return: The chunks to send, in order.
        """
        chunks = [text[i : i + self.MESSAGE_LIMIT] for i in range(0, len(text), self.MESSAGE_LIMIT)] or [""]
        if self.MAX_CHUNKS is not None and len(chunks) > self.MAX_CHUNKS:
            chunks = chunks[: self.MAX_CHUNKS] + [self.TRUNCATION_NOTICE]
        return chunks
