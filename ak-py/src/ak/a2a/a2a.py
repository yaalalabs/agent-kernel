from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater, TaskStore
from a2a.types import UnsupportedOperationError, AgentCard, Part, TextPart, InternalError, Task
from a2a.utils.errors import ServerError

from .. import Agent, AgentService
from ..core import Runtime
from ..core.config import AKConfig


class A2A:
    """
    A2A class provides a utility method for interacting with runtime, agents and sessions.
    """

    """
    A2A cards
    """
    _cards = []
    """
    A2A executors. A2A expects an executor per each agent
    """
    _executors = {}
    """
    A2A skill to agent map needs to be maintained because A2A request only specifies the skill name
    """
    _skill_to_agent_mapping = {}

    class Executor(AgentExecutor, AgentService):

        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            pass

        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            if not context.task_id or not context.context_id:
                raise ValueError("RequestContext must have task_id and context_id")
            if not context.message:
                raise ValueError("RequestContext must have a message")

            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            try:
                response = await self.execute_agent(context.context_id, context.get_user_input())
                parts = [Part(root=TextPart(text=response))]
            except Exception as e:
                parts = [
                    Part(root=TextPart(text="Sorry, Agent Kernel encountered an error while processing your request"))]
                await updater.add_artifact(parts)
                raise ServerError(error=InternalError()) from e

            await updater.add_artifact(parts)
            await updater.complete()

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            raise ServerError(error=UnsupportedOperationError())

        async def execute_agent(self, session_id: str, prompt: str) -> Any:
            AgentService._select(session_id, self.agent_name)
            return await AgentService._run_agent(prompt=prompt)

    @classmethod
    def build(cls):
        if not AKConfig.a2a.enabled:
            return
        agents: dict[str, Agent] = Runtime.instance().agents()
        for name, agent in agents.items():
            whitelisted = AKConfig.a2a.agents == ["*"] or name in AKConfig.a2a.agents
            if not whitelisted:
                continue
            # get card
            card: AgentCard = agent.get_a2a_card()
            cls._cards.append(card)
            skills = card.skills
            # map skills to agents
            for skill in skills:
                cls._skill_to_agent_mapping[skill] = name
            # create executor for agent
            cls._executors[name] = cls.Executor(name)

    @classmethod
    def get_executors(cls) -> dict[str, AgentExecutor]:
        return cls._executors

    @classmethod
    def get_cards(cls) -> list[AgentCard]:
        return cls._cards

    @classmethod
    def get_skill_to_agent_mapping(cls) -> dict[str, str]:
        return cls._skill_to_agent_mapping


class RedisTaskStore(TaskStore):
    # TODO add implementation
    async def save(self, task: Task, context: ServerCallContext | None = None) -> None:
        pass

    async def get(self, task_id: str, context: ServerCallContext | None = None) -> Task | None:
        pass

    async def delete(self, task_id: str, context: ServerCallContext | None = None) -> None:
        pass
