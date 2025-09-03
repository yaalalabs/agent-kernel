import logging
import os
import uuid

from ..core import Runtime, Agent, Session
from ..core.runtime import MemoryType


class AgentService:
    """
    AgentService class provides a utility method for interacting with runtime, agents and sessions.
    """
    _log = logging.getLogger("ak.core.service.agentservice")
    _agent: Agent | None = None
    _session: Session | None = None
    _env_mem = os.getenv("AK_MEMORY")
    _memory_type: MemoryType = MemoryType(_env_mem) if _env_mem else MemoryType.REDIS
    _runtime: Runtime = Runtime.instance(_memory_type)

    @classmethod
    def reset(cls):
        cls._agent = None
        cls._session = None

    @classmethod
    def _select(cls, session_id: str | None, name: str | None = None):
        """
        Selects an agent by name, or the first available agent if no name is provided.
        :param session_id: Unique identifier for the session.
        :param name: Name of the agent to select.
        """
        if name:
            selected = cls._runtime.agents().get(name)
            if selected:
                cls._agent = selected
            else:
                cls._log.warning(f"No agent found with name '{name}'")
        else:
            cls._log.info("No agent was requested. Defaulting to first agent in the list")
            agents = list(cls._runtime.agents().values())
            cls._agent = agents[0] if agents else None
            if cls._agent:
                cls._log.info(f"Selected agent: {cls._agent.name}")
            else:
                cls._log.error("No agents available")

        # Create a session only if an agent is selected
        if cls._agent:
            if session_id is not None:
                cls._old(session_id)
            else:
                cls._new()
        else:
            cls._log.warning("No agent selected. Session was not created.")

    @classmethod
    def _old(cls, session_id: str):
        """
        Attempts to load an existing session.
        :param session_id: Unique identifier for the session.
        """
        cls._log.debug(f"Attempting to reuse existing session: {session_id}")
        cls._session = cls._runtime.sessions().load(session_id)

    @classmethod
    def _new(cls):
        """
        Creates a new session.
        """
        session_id = str(uuid.uuid4())
        cls._log.info(f"Starting new session: {session_id}")
        cls._session = cls._runtime.sessions().new(session_id)

    @classmethod
    def _load(cls, session_id: str, name: str):
        """
        Loads an agent module by name.
        :param session_id: Unique identifier for the session.
        :param name: Name of the agent module to load.
        """
        try:
            cls._runtime.load(name)
            if not cls._agent:
                cls._select(session_id)
        except ImportError as e:
            cls._log.info(f"No module found with name '{name}': {e}")
            return None

    @classmethod
    async def _run_agent(cls, prompt: str):
        """
        Async method to run the agent.
        :param prompt: Prompt to send to the agent.
        """
        result = await cls._runtime.run(cls._agent, cls._session, prompt)
        cls._runtime.sessions().store(cls._session)
        return result

    @classmethod
    def _get_response_session_id(cls, session_id: str | None = None) -> str | None:
        """
        Method will return the session's ID if exists. If not, it will
        return the ID sent by the user. If neither exists, it will return None.
        :param session_id: Unique identifier for the session.
        """
        if cls._session:
            return cls._session.id
        else:
            return session_id

    @staticmethod
    def get_runtime() -> Runtime:
        return AgentService._runtime
