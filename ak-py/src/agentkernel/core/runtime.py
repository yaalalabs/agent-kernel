import importlib
import logging

from enum import StrEnum
from agentkernel.core.builder import SessionStoreBuilder
from singleton_type import Singleton
from types import ModuleType
from typing import Any

from .base import Agent, Session
from .config import AKConfig
from .sessions import InMemorySessionStore, RedisSessionStore, SessionStore
from .sessions.redis import RedisDriver


class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    def __init__(self, sessions: SessionStore):
        self._log = logging.getLogger("ak.runtime")
        self._agents = {}
        self._sessions = sessions

    @staticmethod
    def instance() -> "Runtime":
        return GlobalRuntime()

    def load(self, module: str) -> ModuleType:
        """
        Loads an agent module dynamically.
        :param module: Name of the module to load.
        :return: The loaded module.
        """
        self._log.debug(f"Loading module '{module}'")
        return importlib.import_module(module)

    def agents(self) -> dict[str, Agent]:
        """
        Returns the list of registered agents.
        :return: List of agents.
        """
        return self._agents

    def register(self, agent: Agent) -> None:
        """
        Registers an agent in the runtime.
        :param agent: The agent to register.
        """
        if not self._agents.get(agent.name):
            self._log.debug(f"Registering agent '{agent.name}'")
            self._agents[agent.name] = agent
        else:
            raise Exception(f"Agent with name '{agent.name}' is already registered.")

    def deregister(self, agent: Agent) -> None:
        """
        Deregisters an agent from the runtime.
        :param agent: The agent to deregister.
        """
        if self._agents.get(agent.name):
            self._log.debug(f"Deregistering agent '{agent.name}'")
            del self._agents[agent.name]
        else:
            self._log.warning(f"Agent with name '{agent.name}' is not registered.")

    async def run(self, agent: Agent, session: Session, prompt: Any) -> Any:
        """
        Runs the specified agent with the given prompt.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        self._log.debug(f"Running agent '{agent.name}' with prompt: {prompt}")
        return await agent.runner.run(agent, session, prompt)

    def sessions(self) -> SessionStore:
        """
        Retrieves the session storage.
        :return: The session storage.
        """
        return self._sessions


class GlobalRuntime(Runtime, metaclass=Singleton):
    """
    GlobalRuntime is a singleton instance of Runtime that can be accessed globally.
    """

    _log = logging.getLogger("ak.runtime")

    def __init__(self):
        sessions = SessionStoreBuilder.build()
        super().__init__(sessions)
