import logging

from abc import abstractmethod
from importlib import import_module
from typing import Any

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
        Retrieves a framework specific session object from the session data.
        :param key: The key to retrieve the session object for.
        :return: The framework specific session object associated with the key, or None if the key
        does not exist.
        """
        return self._data.get(key)

    def set(self, key: str, value: Any) -> Any:
        """
        Sets a framework specific session object in the session data.
        :param key: The key to set the session object for.
        :param value: The framework specific session object to set.
        """
        self._data[key] = value
        return value

class Runner:
    """
    Runner is the base class for all agent runners.

    Agent Kernel provides an implementation of the Runner class for each supported agent framework,
    allowing the runtime to execute agent logic in a framework agnostic manner. These
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

class Agent:
    """
    Agent is the base class for all agents.
    
    Agent Kernel provides an implementation of the Agent class for each supported agent framework,
    allowing the runtime to manage agents in a framework agnostic manner. These implementations
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

class Module:
    """
    Module is the base class for all agent modules.
    
    An agent module is a Python module containing a set of agents built using a supported agent
    framework. Agent Kernel provides an implementation of the Module class for each supported agent
    framework, allowing the agents to be registered and managed in a framework agnostic manner.
    """

    def __init__(self, agents: list[Agent]):
        """
        Initializes a Module instance.
        :param agents: List of agents in the module.
        """
        self._agents = agents
        for agent in agents:
            Runtime.register(agent)

    @property
    def agents(self) -> list[Agent]:
        """
        Returns the list of agents in the module.
        """
        return self._agents

class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    _log = logging.getLogger("ak.runtime")
    _agents = {}

    @staticmethod
    def load(module):
        """
        Loads an agent module dynamically.
        :param module: Name of the module to load.
        :return: The loaded module.
        """
        Runtime._log.debug(f"Loading module '{module}'")
        return import_module(module)

    @staticmethod
    def register(agent: Agent):
        """
        Registers an agent in the runtime.
        :param agent: The agent to register.
        """
        if not Runtime._agents.get(agent.name):
            Runtime._log.debug(f"Registering agent '{agent.name}'")
            Runtime._agents[agent.name] = agent
        else:
            Runtime._log.warning(f"Agent with name '{agent.name}' is already registered.")

    @staticmethod
    def agents() -> dict[str, Agent]:
        """
        Returns the list of registered agents.
        :return: List of agents.
        """
        return Runtime._agents

    @staticmethod
    async def run(agent: Agent, session: Session, prompt: Any) -> Any:
        """
        Runs the specified agent with the given prompt.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        Runtime._log.debug(f"Running agent '{agent.name}' with prompt: {prompt}")
        return await agent.runner.run(agent, session, prompt)
