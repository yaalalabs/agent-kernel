import importlib
import logging
import os
from enum import StrEnum
from typing import Any

from .base import Agent, Session
from .sessions import InMemorySessionStore, SessionStore, RedisSessionStore
from .. import RedisDriver


class MemoryType(StrEnum):
    IN_MEMORY = "IN_MEMORY"
    REDIS = "REDIS"


class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    _log = logging.getLogger("ak.runtime")
    _agents = {}
    _sessions: SessionStore = InMemorySessionStore()

    def __init__(self, memory_type: MemoryType = MemoryType.IN_MEMORY):
        if memory_type == "REDIS":
            self._sessions = RedisSessionStore(RedisDriver())
            self._log.debug("Using Redis session store")
        else:
            self._log.debug("Using in-memory session store")
            self._sessions = InMemorySessionStore()

    @staticmethod
    def instance() -> 'Runtime':
        return RUNTIME

    def load(self, module: str) -> None:
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
            self._log.warning(f"Agent with name '{agent.name}' is already registered.")

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


if os.environ.get("AK_MEMORY_TYPE") == "REDIS":
    RUNTIME = Runtime(MemoryType.REDIS)
else:
    RUNTIME = Runtime(MemoryType.IN_MEMORY)
