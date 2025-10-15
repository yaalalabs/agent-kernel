from typing import Any, List

from agents import Agent, Runner
from agents.memory.session import SessionABC

from ..core import Agent as BaseAgent, Module, Runner as BaseRunner, Session

FRAMEWORK = "openai"


class OpenAISession(SessionABC):
    """
    OpenAISession class provides a session for OpenAI Agents SDK-based agents.
    """

    def __init__(self):
        """
        Initializes an OpenAISession instance.
        """
        self._items = []

    async def get_items(self, limit: int | None = None) -> List[dict]:
        """
        Retrieve items stored in this session.
        :param limit: Optional limit on the number of items to retrieve.
        :return: List of items in the session.
        """
        if limit is not None:
            return self._items[:limit]
        return self._items

    async def add_items(self, items: List[dict]) -> None:
        """
        Add items to this session.
        :param items: List of items to add.
        """
        self._items.extend(items)

    async def pop_item(self) -> dict | None:
        """
        Remove and return the most recent item from this session.
        :return: The most recent item, or None if the session is empty.
        """
        if self._items:
            return self._items.pop()
        return None

    async def clear_session(self) -> None:
        """
        Clear all items for this session.
        """
        self._items.clear()


class OpenAIRunner(BaseRunner):
    """
    OpenAIRunner class provides a runner for OpenAI Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an OpenAIRunner instance.
        """
        super().__init__(FRAMEWORK)

    def _session(self, session: Session) -> OpenAISession:
        """
        Returns the OpenAI session associated with the provided session.
        :param session: The session to retrieve the OpenAI session for.
        :return: OpenAISession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, OpenAISession())

    async def run(self, agent: Any, session: Session, prompt: Any) -> Any:
        """
        Runs the OpenAI agent with the provided prompt.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        result = await Runner.run(agent.agent, prompt, session=self._session(session))
        return result.final_output


class OpenAIAgent(BaseAgent):
    """
    OpenAIAgent class provides an agent wrapping for OpenAI Agent SDK based agents.
    """

    def __init__(self, name: str, runner: OpenAIRunner, agent: Agent):
        """
        Initializes an OpenAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The OpenAI agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent

    @property
    def agent(self) -> Agent:
        """
        Returns the OpenAI agent instance.
        """
        return self._agent

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.instructions

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = []
        for tool in self.agent.tools:
            skills.append(AgentSkill(
                id=tool.name,
                name=tool.name,
                description=tool.description,
                tags=[]
            ))
        return self._generate_a2a_card(
            agent_name=self.name,
            description=self.agent.instructions,
            skills=skills
        )


class OpenAIModule(Module):
    """
    OpenAIModule class provides a module for OpenAI Agent SDK based agents.
    """

    def __init__(self, agents: list[Agent]):
        """
        Initializes an OpenAIModule instance.
        :param agents: List of agents in the module.
        """
        runner = OpenAIRunner()
        super().__init__(list(map(lambda agent: OpenAIAgent(agent.name, runner, agent), agents)))
