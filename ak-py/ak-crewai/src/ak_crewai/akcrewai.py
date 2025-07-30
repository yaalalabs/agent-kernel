from typing import Any
from crewai import Agent, Crew, Task
from crewai.memory.external.external_memory import ExternalMemory
from crewai.memory.storage.interface import Storage
from ak import Agent as BaseAgent, Module, Runner, Session

FRAMEWORK = "crewai"
class CrewAISession(Storage):
    """
    CrewAISession class provides a session for CrewAI based agents.
    """

    def __init__(self):
        """
        Initializes a CrewAISession instance.
        """
        self._items = []
        self._memory = ExternalMemory(storage=self)

    @property
    def memory(self) -> ExternalMemory:
        """
        Returns the external memory associated with this session.
        """
        return self._memory

    def save(self, value: Any, metadata=None, agent=None) -> None:
        self._logger.info(f"Saving item: {value} with metadata: {metadata} for agent: {agent}")
        self._items.append({
            "value": value,
            "metadata": metadata,
            "agent": agent
        })

    def search(self, query: str, limit: int = 10, score_threshold: float = 0.5) -> list[dict]:
        """
        Searches for items in the session that match the query.
        :param query: The search query.
        :param limit: Maximum number of results to return.
        :param score_threshold: Minimum score threshold for results.
        :return: List of items matching the query.
        """
        return list(map(lambda item: {"memory": item["value"]}, self._items[:limit]))

    def reset(self) -> None:
        """
        Resets the session by clearing all items.
        """
        self._items = []

class CrewAIRunner(Runner):
    """
    CrewAIRunner class provides a runner for CrewAI based agents.
    """

    def __init__(self):     
        """
        Initializes a CrewAIRunner instance.
        """
        super().__init__(FRAMEWORK)

    def memory(self, session: Session) -> ExternalMemory | None:
        """
        Returns the external memory associated with the session.
        :param session: The session to retrieve the memory for.
        :return: The external memory for the session, or None if the session is not provided.
        """
        if session is None:
            return None
        return (session.get(FRAMEWORK) or session.set(FRAMEWORK, CrewAISession())).memory

    async def run(self, agent: Any, session: Session, prompt: Any) -> Any:
        """
        Runs the CrewAI agent with the provided prompt.
        :param agent: The CrewAI agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        task = Task(
            description=prompt, expected_output="An answer is plain text", agent=agent.agent)
        crew = Crew(agents=agent.crew, tasks=[task], verbose=False, external_memory=self.memory(session))
        return crew.kickoff(inputs={})

class CrewAIAgent(BaseAgent):
    """
    CrewAIAgent class provides an agent wrapping for CrewAI based agents.
    """

    def __init__(self, name: str, runner: CrewAIRunner, agent: Agent, crew: list[Agent]):
        """
        Initializes a CrewAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The CrewAI agent instance.
        :param crew: List of CrewAI agents in the crew.
        """
        super().__init__(name, runner)
        self._agent = agent
        self._crew = crew

    @property
    def agent(self) -> Agent:
        """
        Returns the CrewAI agent instance.
        """
        return self._agent

    @property
    def crew(self) -> list[Agent]:
        """
        Returns the list of CrewAI agents in the crew.
        """
        return self._crew
class CrewAIModule(Module):
    """
    CrewAIModule class provides a module for CrewAI based agents.
    """

    def __init__(self, agents: list[Agent]):
        """
        Initializes a CrewAIModule instance.
        :param agents: List of agents in the module.
        """
        runner = CrewAIRunner()
        super().__init__(
            list(map(lambda agent: CrewAIAgent(agent.role, runner, agent, agents), agents)))
