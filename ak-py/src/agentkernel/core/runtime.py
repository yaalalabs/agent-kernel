import importlib
import logging
import traceback

from enum import StrEnum
from threading import Lock
from types import ModuleType
from typing import Any, Self

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
    _instance: Self  = None
    _lock: Lock = Lock()

    def __init__(self, memory_type: _MemoryType = _MemoryType.IN_MEMORY):
        self._log = logging.getLogger("ak.runtime")
        self._agents = {}
        self._sessions: SessionStore = None
        if memory_type == _MemoryType.REDIS:
            self._sessions = RedisSessionStore(RedisDriver())
            self._log.info("Using Redis session store")
        else:
            self._sessions = InMemorySessionStore()
            self._log.info("Using in-memory session store")

    @staticmethod
    def instance() -> "Runtime":
        if Runtime._instance is None:
            with Runtime._lock:
                if Runtime._instance is None:
                    log = logging.getLogger("ak.runtime")
                    env_mem = AKConfig.get().session.type.upper()
                    try:
                        memory_type: _MemoryType = _MemoryType(env_mem) if env_mem else _MemoryType.IN_MEMORY
                    except ValueError:
                        log.warning(f"Invalid memory type '{env_mem}', falling back to IN_MEMORY")
                        log.warning(traceback.format_exc())
                        memory_type = _MemoryType.IN_MEMORY
                    log.debug(f"Using memory type: {memory_type}")
                    Runtime._instance = Runtime(memory_type)
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
