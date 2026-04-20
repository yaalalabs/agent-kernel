import logging
from typing import Any

from langfuse import Langfuse, propagate_attributes
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.adk.adk import GoogleADKRunner


class LangFuseADKRunner(GoogleADKRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFuseADKRunner instance.
        :param client: The Langfuse client instance.
        """
        super().__init__()
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.adk")

        GoogleADKInstrumentor().instrument()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the ADK agent with provided multi modal inputs.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        with propagate_attributes(session_id=session.id, tags=["agentkernel"]):

            with self._client.start_as_current_observation(name="Agent Kernel ADK", as_type="span") as span:

                result = await super().run(agent, session, requests)
                span.update(input=result.prompt, output=str(result))

        return result
