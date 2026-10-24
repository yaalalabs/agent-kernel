import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from a2a.helpers import new_data_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types import AgentCard, InternalError, Message, UnsupportedOperationError

from ...a2ui.hook import A2UIPostHook
from ...core import Agent
from ...core.config import AKConfig
from ...core.model import BaseRunRequest
from ...core.runtime import Runtime

if TYPE_CHECKING:  # pragma: no cover: annotation only; api reaches pipeline lazily
    from ...pipeline.request_client import QueuedReply, QueueRequestClient


class A2A:
    """
    A2A class provides a utility method for interacting with runtime, agents and sessions.

    Agents never run here: each executor puts the request on the input queue and waits for the
    runner's whole reply in the response store (#780).
    """

    PROTOCOL = "a2a"
    """
    Value of the queue message's ``protocol`` attribute for A2A requests
    """

    _cards: dict[str, AgentCard] = {}
    """
    A2A cards
    """
    _executors: dict[str, "A2A.Executor"] = {}
    """
    A2A executors. A2A expects an executor per each agent
    """
    _built = False
    """
    Card built flag
    """
    _client: Optional["QueueRequestClient"] = None
    """
    The surface's one queue client, built on first use
    """
    _log = logging.getLogger("ak.a2a")

    class Executor(AgentExecutor):
        """Answers an A2A message with the agent's reply, run on the agent runner through the queue.

        The session is the A2A ``context_id``. The caller gets one message: a data part for a
        structured payload with a media type, otherwise a text part (a structured payload without a
        media type as JSON text). Failures raise ``InternalError`` carrying a generic message, which
        is all the caller reads; their details go to the log only.
        """

        ERROR_MESSAGE = "Sorry, Agent Kernel encountered an error while processing your request"
        TIMEOUT_MESSAGE = "Timed out waiting for the agent's reply"

        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            self.log = logging.getLogger(f"ak.a2a.executor.{agent_name}")

        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            from ...pipeline.request_client import ReplyTimeoutError

            if not context.task_id or not context.context_id:
                raise ValueError("RequestContext must have task_id and context_id")
            if not context.message:
                raise ValueError("RequestContext must have a message")

            body = BaseRunRequest(prompt=context.get_user_input(), agent=self.agent_name, session_id=context.context_id)
            try:
                reply = await A2A.get_client().request(body, protocol=A2A.PROTOCOL)
            except ReplyTimeoutError as e:
                self.log.error(f"No reply within the wait budget: request_id={e.request_id}, retry_count={e.retry_count}, delay={e.delay}")
                raise InternalError(message=self.TIMEOUT_MESSAGE) from e
            except Exception as e:
                self.log.exception(f"Agent request failed: {e}")
                raise InternalError(message=self.ERROR_MESSAGE) from e

            if reply.is_error or reply.result is None:
                self.log.error(f"Agent reply failed: request_id={reply.request_id}, status_code={reply.status_code}, error={reply.error}")
                raise InternalError(message=self.ERROR_MESSAGE)

            await event_queue.enqueue_event(self._as_message(reply, context))

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            raise UnsupportedOperationError()

        @classmethod
        def _as_message(cls, reply: "QueuedReply", context: RequestContext) -> Message:
            """The reply as one A2A message.

            A structured result with a media type becomes a data part labelled in both places a
            client may look: the part's own ``media_type`` and ``metadata["mimeType"]``, the key
            the A2UI binding names. Everything else is one text part, as before data parts existed.
            Ids go by keyword: both helpers take ``media_type`` second.
            """
            if reply.media_type and isinstance(reply.result, (dict, list)):
                data = A2UIPostHook.a2a_data(reply.media_type, reply.result)
                message = new_data_message(data, media_type=reply.media_type, context_id=context.context_id, task_id=context.task_id)
                message.parts[0].metadata.update({"mimeType": reply.media_type})
                return message
            return new_text_message(cls._as_text(reply.result), context_id=context.context_id, task_id=context.task_id)

        @staticmethod
        def _as_text(result: Any) -> str:
            """A text reply as is; a structured one as JSON text, the same text ``str(AgentReplyAny)`` gives."""
            return result if isinstance(result, str) else json.dumps(result)

    @classmethod
    def get_client(cls) -> "QueueRequestClient":
        """The surface's one queue client, built on first use.

        Imported here, not at module scope: ``api`` reaches ``pipeline`` lazily, as ``RESTAPI.run`` does.
        """
        if cls._client is None:
            from ...pipeline.request_client import QueueRequestClient

            cls._client = QueueRequestClient()
        return cls._client

    @classmethod
    def _build(cls):
        if cls._built:
            return
        if not AKConfig.get().a2a.enabled:
            return
        agents: dict[str, Agent] = Runtime.current().agents()
        for name, agent in agents.items():
            whitelisted = AKConfig.get().a2a.agents == ["*"] or name in AKConfig.get().a2a.agents
            if not whitelisted:
                continue
            # get card
            card: Optional[AgentCard] = agent.get_a2a_card()
            if card is None:
                cls._log.warning(f"Agent '{name}' has no A2A card; it is not served over A2A")
                continue
            cls._cards.update({name: card})
        cls._built = True

    @classmethod
    def get_executor(cls, agent_name: str) -> AgentExecutor:
        if cls._executors.get(agent_name) is None:
            cls._executors[agent_name] = cls.Executor(agent_name)
        executor: A2A.Executor = cls._executors[agent_name]
        return executor

    @classmethod
    def get_cards(cls) -> list[AgentCard]:
        cls._build()
        return list(cls._cards.values())

    @classmethod
    def get_card(cls, name: str) -> AgentCard:
        cls._build()
        return cls._cards.get(name)

    @classmethod
    def get_agent_names(cls) -> list[str]:
        cls._build()
        return list(cls._cards.keys())

    @classmethod
    def get_task_store(cls) -> TaskStore:
        return RedisTaskStore() if AKConfig.get().a2a.task_store_type == "redis" else InMemoryTaskStore()


class RedisTaskStore(InMemoryTaskStore):
    pass
