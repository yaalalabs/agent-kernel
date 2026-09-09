import logging
from typing import Any

import logfire
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.adk.adk import GoogleADKRunner


class LogfireADKRunner(GoogleADKRunner):

    def __init__(self):
        """
        Initializes a LogfireADKRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.logfire.adk")

        GoogleADKInstrumentor().instrument()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the ADK agent with provided multi modal inputs.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with logfire.span("Agent Kernel ADK", session_id=session.id) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute("input", result.prompt)
            span.set_attribute("output", str(result))
        return result
