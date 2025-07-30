from typing import Any, List
from agents import Agent, Runner

from ak import Agent as BaseAgent, Module, Runner as BaseRunner, Session as BaseSession

class OpenAISession(BaseSession):
    """
    OpenAISession class provides a session for OpenAI Agents SDK based agents.
    """

    def __init__(self, id: str):
        """
        Initializes an OpenAISession instance.
        :param id: Unique identifier for the session.
        """
        super().__init__(id)
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
        super().__init__("openai")

    def session(self, id: str) -> OpenAISession:
        """
        Create a new OpenAISession with the given identifier.
        :param id: Unique identifier for the session.
        :return: OpenAISession instance.
        """
        return OpenAISession(id)

    async def run(self, agent: Any, session: Any, prompt: Any) -> Any:
        """
        Runs the OpenAI agent with the provided prompt.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        result = await Runner.run(agent.agent, prompt, session=session)
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

class OpenAIModule(Module):
    """
    OpenAIModule class provides a module for OpenAI Agent SDK based agents.
    """

    def __init__(self, agents: list[Agent]):
        """
        Initializes a OpenAIModule instance.
        :param agents: List of agents in the module.
        """
        runner = OpenAIRunner()
        super().__init__(list(map(lambda agent: OpenAIAgent(agent.name, runner, agent), agents)))
