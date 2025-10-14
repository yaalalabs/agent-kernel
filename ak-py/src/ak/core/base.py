import logging
from abc import abstractmethod, ABC
from typing import Any, List

from .config import AKConfig


class Session:
    """
    Session is the base class for a stacking state across related interactions with agents.

    Agent Kernel provides an implementation of the Session class for each supported agent framework,
    allowing the runtime to track and share state across multiple related agent logic invocations.

    Sessions may be volatile (meaning that they are not persisted) or durable (meaning that they
    are persisted and are available across multiple invocations of the runtime). This is governed by
    the runtime configuration.
    """

    def __init__(self, id: str):
        """
        Initializes a Session instance.
        :param id: Unique identifier for the session.
        """
        self._log = logging.getLogger("ak.core.session")
        self._id = id
        self._data = {}

    @property
    def id(self) -> str:
        """
        Returns the unique identifier for the session.
        :return: Unique identifier for the session.
        """
        return self._id

    def get(self, key: str) -> Any:
        """
        Retrieves a framework-specific session object from the session data.
        :param key: The key to retrieve the session object for.
        :return: The framework-specific session object associated with the key, or None if the key
        does not exist.
        """
        result = self._data.get(key)
        self._log.debug(f"Retrieved session object for key {key}: {result}")
        return result

    def get_all_keys(self):
        """
        Returns a list of all keys in the session data.
        :return: A list of all keys in the session data.
        """
        return self._data.keys()

    def set(self, key: str, value: Any) -> Any:
        """
        Sets a framework-specific session object in the session data.
        :param key: The key to set the session object for.
        :param value: The framework-specific session object to set.
        """
        self._log.debug(f"Setting session object for key {key}: {value}")
        self._data[key] = value
        return value


class Runner(ABC):
    """
    Runner is the base class for all agent runners.

    Agent Kernel provides an implementation of the Runner class for each supported agent framework,
    allowing the runtime to execute agent logic in a framework-agnostic manner. These
    implementations inherit from the Runner class and encapsulate the agent runner provided by that
    framework.
    """

    def __init__(self, name: str):
        """
        Initializes a Runner instance.
        :param name: Name of the runner.
        """
        self._name = name

    @property
    def name(self) -> str:
        """
        Returns the name of the runner.
        """
        return self._name

    @abstractmethod
    async def run(self, agent: Any, session: Session, prompt: Any) -> Any:
        """
        Runs the agent with the provided prompt.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        pass


class Agent(ABC):
    """
    Agent is the base class for all agents.
    
    Agent Kernel provides an implementation of the Agent class for each supported agent framework,
    allowing the runtime to manage agents in a framework-agnostic manner. These implementations
    inherit from the Agent class and encapsulate the agent implementation provided by that
    framework.
    """

    def __init__(self, name: str, runner: Runner):
        """
        Initializes an Agent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        """
        self._name = name
        self._runner = runner

    @property
    def name(self) -> str:
        """
        Returns the name of the agent.
        """
        return self._name

    @property
    def runner(self) -> Runner:
        """
        Returns the runner associated with the agent.
        """
        return self._runner

    @staticmethod
    def _generate_a2a_card(agent_name: str, description: str, skills: List):
        """
        Helper method to generate an A2A AgentCard.
        :param agent_name: Name of the agent.
        :param description: Description of the agent.
        :param skills: List of AgentSkill objects.
        :return: An A2A AgentCard instance.
        """
        from a2a.types import AgentCard, AgentCapabilities
        return AgentCard(
            name=agent_name,
            description=description,
            url=f'{AKConfig.get().a2a.url}/{agent_name}',
            version=AKConfig.get().library_version,
            default_input_modes=["text"],
            default_output_modes=["json"],
            preferred_transport="HTTP+JSON",
            capabilities=AgentCapabilities(streaming=False),
            skills=skills
        )

    @abstractmethod
    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        pass

    @abstractmethod
    def get_description(self):
        """
        Returns the description of the agent.
        """
        pass
