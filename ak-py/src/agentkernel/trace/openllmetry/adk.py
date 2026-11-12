import logging
from typing import Any

from ...core import Agent, Session
from ...core.model import AgentReply, AgentRequest
from ...framework.adk.adk import GoogleADKRealtimeRunner, GoogleADKRunner
from ..base import RealtimeCallSpan, TracedRealtimeRunner
from .openllmetry import OpenLLMetryRealtimeCallSpan, TraceloopContext


class OpenLLMetryADKRunner(GoogleADKRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryADKRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.adk")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the ADK agent with provided multi modal inputs.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel ADK", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result


class OpenLLMetryADKRealtimeRunner(TracedRealtimeRunner, GoogleADKRealtimeRunner):
    """
    The ADK realtime runner with one OpenLLMetry span over each call, tagged with the session id as this provider's ``run()`` span is.
    """

    SPAN_NAME = "Agent Kernel ADK realtime"

    def _start_call_span(self, session: Session, agent: Agent) -> RealtimeCallSpan:
        return OpenLLMetryRealtimeCallSpan(self.SPAN_NAME, session.id)
