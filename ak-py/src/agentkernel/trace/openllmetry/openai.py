import logging
from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.openai.openai import OpenAIRunner
from .openllmetry import TraceloopContext


class OpenLLMetryOpenAIRunner(OpenAIRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryOpenAIRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.openai")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the OpenAI agent with provided multi modal inputs.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel OpenAI", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result
