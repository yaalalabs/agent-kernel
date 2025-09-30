import logging
from typing import Any
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
from ak.core import Agent, Module, Runner as BaseRunner, Session

FRAMEWORK = "adk"
APP_NAME = "google_adk"

class GoogleADKSession(Session):
    """Manages Google ADK user sessions and underlying session service."""
    def __init__(self):
        """Initialize the session store and logging for Google ADK sessions."""
        super().__init__(FRAMEWORK)
        self._session_service = InMemorySessionService()
        self._sessions = {}
        self._log = logging.getLogger("ak.adk.session")

    @property
    def session_service(self):
        """Return the in-memory session service instance."""
        return self._session_service

    async def create_or_use_existing(self, custom_app_name: str = None, initial_state: dict = None):
        """Create a new session or return an existing one.

        :param custom_app_name: Optional app name to namespace the session.
        :param initial_state: Optional initial state for a new session.
        :return: Tuple of (session_id, session object).
        """
        app_name = custom_app_name or APP_NAME
        session_id = f"{self.id}-{custom_app_name}" if custom_app_name else f"{self.id}-{APP_NAME}"

        if session_id in self._sessions:
            self._log.debug(f"Session already exists for ID: {session_id}")
            return session_id, self._sessions[session_id]

        self._log.debug(f"Creating session with ID: {session_id}, AppName: {app_name}, InitialState: {initial_state}")
        session = await self._session_service.create_session(
            app_name=app_name,
            user_id=session_id,
            session_id=session_id,
            state=initial_state,
        )

        self._log.debug(f"Created Session: {session}")
        self._sessions[session_id] = session
        return session_id, session


class GoogleADKRunner(BaseRunner):
    def __init__(self):
        """
        Initializes an GoogleADKRunner instance.
        """
        super().__init__(FRAMEWORK)

    def _session(self, session: Session) -> GoogleADKSession:
        """
        Returns the GoogleADK session associated with the provided session.
        :param session: The session to retrieve the GoogleADK session for.
        :return: GoogleADKSession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, GoogleADKSession())

    def _create_runner(self, agent:'GoogleADKAgent', session:GoogleADKSession, use_agentname_for_appname=False):
        """Build a Google ADK Runner wired to the given agent and session."""
        return Runner(agent=agent.agent, app_name=agent.name if use_agentname_for_appname else APP_NAME, session_service=session.session_service)

    async def get_agent_response(self, runner: Runner, session_id: str, message_text: str) -> str:
        """Send a message to the agent and return the final response text asynchronously."""
        new_message = types.Content(role="user", parts=[types.Part(text=message_text)])
        response_text = None
        async for event in runner.run_async(user_id=session_id, session_id=session_id, new_message=new_message):
            if event.is_final_response() and event.content and event.content.parts:
                text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                response_text = " ".join(text_parts) if text_parts else None
                break
        return response_text

    async def run(self, agent: Any, session: Session, prompt: Any) -> Any:
        """Run the agent with the given prompt and return the response text."""
        google_adk_session = self._session(session)
        runner = self._create_runner(agent=agent, session=google_adk_session, use_agentname_for_appname=True)
        session_id, _ = await google_adk_session.create_or_use_existing(custom_app_name=agent.name)
        return await self.get_agent_response(runner=runner, session_id=session_id, message_text=prompt)


class GoogleADKAgent(Agent):
    """
    GoogleADKAgent class provides an agent wrapping for GoogleADK Agent SDK based agents.
    """

    def __init__(self, name:str, runner:GoogleADKRunner, agent:Agent):
        """
        Initializes an GoogleADKAgent instance.
        :param name: Name of the agent.
        :param runner: BaseRunner associated with the agent.
        :param agent: The GoogleADK agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent

    @property
    def agent(self) -> Agent:
        """
        Returns the GoogleADK agent instance.
        """
        return self._agent


class GoogleADKModule(Module):
    """
    GoogleADKModule class provides a module for GoogleADK based agents.
    """
    def __init__(self, agents: list[Agent]):
        """
        Initializes an GoogleADKModule instance.
        :param agents: List of agents in the module.
        """
        runner = GoogleADKRunner()
        super().__init__(list(map(lambda agent: GoogleADKAgent(agent.name, runner, agent), agents)))