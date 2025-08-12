import logging
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
        self._log = logging.getLogger("akcrewai.session")

    def save(self, value: Any, metadata=None, agent=None) -> None:
        self._log.debug(f"save: {value}, {metadata}, {agent}")
        if metadata is None:
            metadata = {}
        if agent is None:
            agent = "Unknown"
        self._items.append({
            "value": value,
            "metadata": metadata,
            "agent": agent
        })

    def search(self, query: str, limit: int = 10, score_threshold: float = 0.5) -> list[dict]:
        self._log.debug(f"search: {query}, {limit}, {score_threshold}")
        """
        Searches for items in the session that match the query.
        :param query: The search query.
        :param limit: Maximum number of results to return.
        :param score_threshold: Minimum score threshold for results.
        :return: List of items matching the query.
        """
        return list(map(lambda item: {"context": item["value"]}, self._items[:limit]))

    def reset(self) -> None:
        self._log.debug("reset")
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
        self._log = logging.getLogger("akcrewai.runner")

    def _memory(self, session: Session) -> ExternalMemory | None:
        """
        Returns the external memory associated with the session.
        :param session: The session to retrieve the memory for.
        :return: The external memory for the session, or None if the session is not provided.
        """
        if session is None:
            self._log.debug("Running without session")
            return None
        if session.get(FRAMEWORK) is None:
            self._log.debug("Creating new CrewAISession")
            shared_session = session.set(FRAMEWORK, CrewAISession())
            return ExternalMemory(storage=shared_session) # ExternalMemory cannot be reshared across crews
        else:
            self._log.debug("Reusing existing CrewAISession")
            shared_session = session.get(FRAMEWORK)
            return ExternalMemory(storage=shared_session)

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
        crew = Crew(agents=agent.crew, tasks=[task], verbose=False, external_memory=self._memory(session))
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
