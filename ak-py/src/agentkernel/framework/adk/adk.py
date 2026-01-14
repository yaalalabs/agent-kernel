from __future__ import annotations

import base64
import logging
from typing import Any, List

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService
from google.genai import types

from agentkernel.core.model import (
    AgentReply,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)

from ...core import Agent as AKBaseAgent
from ...core import Module, PostHook, PreHook
from ...core import Runner as BaseRunner
from ...core import Session
from ...core.config import AKConfig
from ...trace import Trace

FRAMEWORK = "adk"


class GoogleADKSession:
    """
    Manages Google ADK user sessions and underlying session service.
    """

    def __init__(self):
        """
        Initialize the session store and logging for Google ADK sessions.
        """
        self._session_service = InMemorySessionService()
        self._log = logging.getLogger("ak.adk.session")
        self._session = None

    @property
    def session_service(self) -> BaseSessionService:
        """
        Return the in-memory session service instance.
        """
        return self._session_service

    async def create_session(self, app_name: str, user_id: str, session_id: str) -> Any:
        if self._session is None:
            self._session = await self._session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
        return self._session


class GoogleADKRunner(BaseRunner):
    def __init__(self):
        """
        Initializes a GoogleADKRunner instance.
        """
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> GoogleADKSession | None:
        """
        Returns the Google ADK session associated with the provided session.
        :param session: The session to retrieve the Google ADK session for.
        :return: GoogleADKSession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, GoogleADKSession())

    @staticmethod
    async def get_response(runner: Runner, user_id: str, session_id: str, parts: list[types.Part]) -> str:
        """
        Send a message to the agent and return the final response text asynchronously.
        :param runner: The Google ADK Runner to use for the agent.
        :param user_id: The user ID to use for the agent.
        :param session_id: The session ID to use for the agent.
        :param parts: The message parts to send to the agent.
        :return: The final response text from the agent.
        """
        new_message = types.Content(role="user", parts=parts)
        response_text = None
        for event in runner.run(user_id=user_id, session_id=session_id, new_message=new_message):
            if event.is_final_response() and event.content and event.content.parts:
                text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                response_text = " ".join(text_parts) if text_parts else None
                break
        return response_text

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the ADK agent with provided multi modal inputs.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
        parts = []

        try:
            for req in requests:
                if isinstance(req, AgentRequestAny):  # AgentRequestAny is handled only by pre-hooks, not by the agent itself
                    continue

                if isinstance(req, AgentRequestText):
                    text = req.text
                    prompt = prompt + "\n" + text if prompt else text
                    parts.append(types.Part(text=text))

                if isinstance(req, (AgentRequestImage, AgentRequestFile)):
                    base64_data = ""
                    if isinstance(req, AgentRequestImage):
                        # Handle image requests - Google ADK expects inline_data format
                        if not req.image_data:
                            raise ValueError("no image input provided")
                        base64_data = req.image_data

                    elif isinstance(req, AgentRequestFile):
                        # Handle file attachments
                        if not req.file_data:
                            raise ValueError("no file input provided")
                        base64_data = req.file_data

                    # if its a URI directly use base64_data as is
                    if base64_data.startswith(("http://", "https://", "s3://")):
                        parts.append(types.Part(file_data=types.FileData(file_uri=base64_data)))
                        continue

                    # If it's base64 and does have the data URI prefix
                    if base64_data.startswith(("data:")):
                        mime_type = base64_data.split(";")[0][5:]  # Extract mime type from data URI
                    else:
                        if not req.mime_type:
                            raise ValueError("mime_type is missing for image input")
                        mime_type = req.mime_type

                    # Google ADK expects inline_data with mime_type and raw data
                    raw_data = base64.b64decode(base64_data.split(",")[-1]) if base64_data.startswith("data:") else base64.b64decode(base64_data)
                    parts.append(types.Part(inline_data=types.Blob(mime_type=mime_type, data=raw_data)))

            if not parts:
                return AgentReplyText(text="Sorry. No valid content found in the requests")

            app_name = "AgentKernel"
            user_id = "AgentKernel"
            adk_session = self._session(session)

            await adk_session.create_session(app_name=app_name, user_id=user_id, session_id=session.id)
            runner = Runner(agent=agent.agent, app_name=app_name, session_service=adk_session.session_service)
            reply = await self.get_response(runner=runner, session_id=session.id, parts=parts, user_id=user_id)

            return AgentReplyText(text=reply, prompt=prompt)
        except Exception as e:
            return AgentReplyText(text=f"Error during agent execution: {str(e)}")


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

    def __init__(self, agents: list[BaseAgent], runner: GoogleADKRunner = None):
        """
        Initializes a Google ADK Module instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().adk()
        else:
            self.runner = GoogleADKRunner()
        self.load(agents)

    def _wrap(self, agent: BaseAgent, agents: List[BaseAgent]) -> AKBaseAgent:
        """
        Wraps the provided agent in a GoogleADKAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: GoogleADKAgent instance.
        """
        return GoogleADKAgent(agent.name, self.runner, agent)

    def load(self, agents: list[BaseAgent]) -> "GoogleADKModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: GoogleADKModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: BaseAgent, hooks: list[PreHook]) -> "GoogleADKModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: GoogleADKModule instance.
        """
        super().get_agent(agent.name).attach_pre_hooks(hooks)
        return self

    def post_hook(self, agent: BaseAgent, hooks: list[PostHook]) -> "GoogleADKModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: GoogleADKModule instance.
        """
        super().get_agent(agent.name).attach_post_hooks(hooks)
        return self
