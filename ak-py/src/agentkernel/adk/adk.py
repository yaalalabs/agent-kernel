import logging
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session as ADKSession
from google.genai import types

from agentkernel.core import Agent as AKBaseAgent, Module, Runner as BaseRunner, Session

FRAMEWORK = "adk"


class GoogleADKSession(Session):
    """
    Manages Google ADK user sessions and underlying session service.
    """

    def __init__(self):
        """
        Initialize the session store and logging for Google ADK sessions.
        """
        super().__init__(FRAMEWORK)
        self._session_service = InMemorySessionService()
        self._sessions = {}
        self._log = logging.getLogger("ak.adk.session")

    @property
    def session_service(self):
        """
        Return the in-memory session service instance.
        """
        return self._session_service

    async def get_adk_session(self, app_name: str) -> tuple[str, ADKSession]:
        """
        Create a new session or return an existing one.
        :param app_name: app name to namespace the session.
        :return: Tuple of (session_id, session object).
        """
        session_id = f"{self.id}-{app_name}"

        if session_id in self._sessions:
            self._log.debug(f"Session already exists for ID: {session_id}")
            return session_id, self._sessions[session_id]

        self._log.debug(f"Creating session with ID: {session_id}, AppName: {app_name}")
        session = await self._session_service.create_session(
            app_name=app_name,
            user_id=session_id,
            session_id=session_id,
        )

        self._log.debug(f"Created Session: {session}")
        self._sessions[session_id] = session
        return session_id, session


class GoogleADKRunner(BaseRunner):
    def __init__(self):
        """
        Initializes a GoogleADKRunner instance.
        """
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> GoogleADKSession:
        """
        Returns the Google ADK session associated with the provided session.
        :param session: The session to retrieve the Google ADK session for.
        :return: GoogleADKSession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, GoogleADKSession())

    @staticmethod
    def _create_runner(agent: 'GoogleADKAgent', session: GoogleADKSession):
        """
        Build a Google ADK Runner wired to the given agent and session.
        :param agent: The Google ADK agent to run.
        :param session: The session to use for the agent.
        """
        return Runner(agent=agent.agent, app_name=agent.name, session_service=session.session_service)

    @staticmethod
    async def get_agent_response(runner: Runner, session_id: str, prompt: str) -> str:
        """
        Send a message to the agent and return the final response text asynchronously.
        :param runner: The Google ADK Runner to use for the agent.
        :param session_id: The session ID to use for the agent.
        :param prompt: The message text to send to the agent.
        :return: The final response text from the agent.
        """
        new_message = types.Content(role="user", parts=[types.Part(text=prompt)])
        response_text = None
        async for event in runner.run_async(user_id=session_id, session_id=session_id, new_message=new_message):
            if event.is_final_response() and event.content and event.content.parts:
                text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                response_text = " ".join(text_parts) if text_parts else None
                break
        return response_text

    async def run(self, agent: Any, session: Session, prompt: Any) -> Any:
        """
        Run the agent with the given prompt and return the response text.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to send to the agent.
        :return: The response text from the agent.
        """
        adk_session = self._session(session)
        runner = self._create_runner(agent=agent, session=adk_session)
        session_id, _ = await adk_session.get_adk_session(app_name=agent.name)
        return await self.get_agent_response(runner=runner, session_id=session_id, prompt=prompt)


class GoogleADKAgent(AKBaseAgent):
    """
    GoogleADKAgent class provides an agent wrapping for Google ADK Agent SDK based agents.
    """

    def __init__(self, name: str, runner: GoogleADKRunner, agent: BaseAgent):
        """
        Initializes a GoogleADKAgent instance.
        :param name: Name of the agent.
        :param runner: BaseRunner associated with the agent.
        :param agent: The Google ADK agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent

    @property
    def agent(self) -> BaseAgent:
        """
        Returns the GoogleADK agent instance.
        """
        return self._agent

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.description

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        # TODO Add A2A card support
        pass


class GoogleADKModule(Module):
    """
    GoogleADKModule class provides a module for Google ADK-based agents.
    """

    def __init__(self, agents: list[BaseAgent]):
        """
        Initializes a Google ADK Module instance.
        :param agents: List of agents in the module.
        """
        runner = GoogleADKRunner()
        super().__init__(list(map(lambda agent: GoogleADKAgent(agent.name, runner, agent), agents)))
