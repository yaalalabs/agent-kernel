import importlib
import logging
import traceback
from enum import StrEnum
from types import ModuleType
from typing import Any

from .base import Agent, Session
from .config import AKConfig
from .sessions import InMemorySessionStore, SessionStore, RedisSessionStore
from .sessions.redis import RedisDriver


class _MemoryType(StrEnum):
    IN_MEMORY = "IN_MEMORY"
    REDIS = "REDIS"


class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    _log = logging.getLogger("ak.runtime")
    _instance = None
    _agents = {}
    _sessions: SessionStore = None
    _memory_type: _MemoryType = None

    def __init__(self, memory_type: _MemoryType = _MemoryType.IN_MEMORY):
        Runtime._memory_type = memory_type
        if Runtime._instance is not None:
            raise Exception("Runtime is a singleton class")
        if memory_type == _MemoryType.REDIS:
            self._sessions = RedisSessionStore(RedisDriver())
            self._log.info("Using Redis session store")
        else:
            self._log.info("Using in-memory session store")
            self._sessions = InMemorySessionStore()
        Runtime._instance = self

    @staticmethod
    def instance() -> "Runtime":
        if Runtime._instance is None:
            env_mem = AKConfig.get().session.type.upper()
            try:
                memory_type: _MemoryType = _MemoryType(env_mem) if env_mem else _MemoryType.IN_MEMORY
            except ValueError:
                Runtime._log.warning(f"Invalid memory type '{env_mem}', falling back to IN_MEMORY")
                Runtime._log.warning(traceback.format_exc())
                memory_type = _MemoryType.IN_MEMORY
            Runtime._log.debug(f"Using memory type: {memory_type}")
            Runtime(memory_type)
        return Runtime._instance

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
