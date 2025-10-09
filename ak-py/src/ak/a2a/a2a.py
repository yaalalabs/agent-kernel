import logging
import traceback
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types import UnsupportedOperationError, AgentCard, InternalError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError

from ..core import Agent, AgentService, Runtime
from ..core.config import AKConfig


class A2A:
    """
    A2A class provides a utility method for interacting with runtime, agents and sessions.
    """
    _cards: dict[str, AgentCard] = {}
    """
    A2A cards
    """
    _executors: dict[str, 'A2A.Executor'] = {}
    """
    A2A executors. A2A expects an executor per each agent
    """
    _built = False
    """
    Card built flag
    """
    _log = logging.getLogger(__name__)

    class Executor(AgentExecutor):

        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            self.log = logging.getLogger(f"ak.a2a.executor.{agent_name}")

        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            if not context.task_id or not context.context_id:
                raise ValueError("RequestContext must have task_id and context_id")
            if not context.message:
                raise ValueError("RequestContext must have a message")
            try:
                response = await self._execute_agent(context.context_id, context.get_user_input())
                await event_queue.enqueue_event(
                    new_agent_text_message(str(response), context.context_id, context.task_id))
            except Exception as e:
                error = "Sorry, Agent Kernel encountered an error while processing your request"
                self.log.error(traceback.format_exc())
                self.log.error(f'Exception: {e}')
                await event_queue.enqueue_event(new_agent_text_message(error, context.context_id, context.task_id))
                raise ServerError(error=InternalError()) from e

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            raise ServerError(error=UnsupportedOperationError())

        async def _execute_agent(self, session_id: str, prompt: str) -> Any:
            service = AgentService()
            service.select(session_id, self.agent_name)
            return await service.run(prompt=prompt)

    @classmethod
    def _build(cls):
        if cls._built:
            return
        if not AKConfig.get().a2a.enabled:
            return
        agents: dict[str, Agent] = Runtime.instance().agents()
        for name, agent in agents.items():
            whitelisted = AKConfig.get().a2a.agents == ["*"] or name in AKConfig.get().a2a.agents
            if not whitelisted:
                continue
            # get card
            card: AgentCard = agent.get_a2a_card()
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
