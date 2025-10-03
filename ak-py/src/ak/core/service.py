import logging
import uuid

from ..core import Runtime, Agent, Session


class AgentService:
    """
    AgentService class provides a utility method for interacting with runtime, agents and sessions.
    The agent service encapsulates a conversation of a single session with a single agent.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.core.service.agentservice")
        self._agent = None
        self._session = None
        self._runtime = Runtime.instance()

    @property
    def runtime(self) -> Runtime:
        """
        Returns the runtime instance.
        """
        return self._runtime

    @property
    def agent(self) -> Agent:
        """
        Returns the selected agent.
        """
        return self._agent

    @property
    def session(self) -> Session:
        """
        Returns the selected session.
        """
        return self._session

    def reset(self):
        """
        Resets the selected agent and session to reuse the agent service instance for sequential runs.
        """
        self._agent = None
        self._session = None

    def select(self, session_id: str | None = None, name: str | None = None):
        """
        Selects an agent by name, or the first available agent if no name is provided.
        :param session_id: Unique identifier for the session.
        :param name: Name of the agent to select.
        """
        if name:
            selected = self._runtime.agents().get(name)
            if selected:
                self._agent = selected
            else:
                self._log.warning(f"No agent found with name '{name}'")
        else:
            self._log.info("No agent was requested. Defaulting to first agent in the list")
            agents = list(self._runtime.agents().values())
            self._agent = agents[0] if agents else None
            if self._agent:
                self._log.info(f"Selected agent: {self._agent.name}")
            else:
                self._log.error("No agents available")

        # Create a session only if an agent is selected
        if self._agent:
            if session_id is not None:
                self._old(session_id)
            else:
                self.new()
        else:
            self._log.warning("No agent selected. Session was not created.")

    def _old(self, session_id: str):
        """
        Attempts to load an existing session.
        :param session_id: Unique identifier for the session.
        """
        self._log.debug(f"Attempting to reuse existing session: {session_id}")
        self._session = self._runtime.sessions().load(session_id)

    def new(self):
        """
        Creates a new session.
        """
        session_id = str(uuid.uuid4())
        self._log.info(f"Starting new session: {session_id}")
        self._session = self._runtime.sessions().new(session_id)

    def load(self, session_id: str, name: str):
        """
        Loads an agent module by name.
        :param session_id: Unique identifier for the session.
        :param name: Name of the agent module to load.
        """
        try:
            self._runtime.load(name)
            if not self._agent:
                self.select(session_id)
        except ImportError as e:
            self._log.info(f"No module found with name '{name}': {e}")
            return None

    async def run(self, prompt: str):
        """
        Async method to run the agent.
        :param prompt: Prompt to send to the agent.
        """
        result = await self._runtime.run(self._agent, self._session, prompt)
        self._runtime.sessions().store(self._session)
        return result

    def get_response_session_id(self, session_id: str | None = None) -> str | None:
        """
        Method will return the session's ID if exists. If not, it will
        return the ID sent by the user. If neither exists, it will return None.
        :param session_id: Unique identifier for the session.
        """
        if self._session:
            return self._session.id
        else:
            return session_id
