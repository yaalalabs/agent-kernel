import logging
from typing import Any

import logfire
from opentelemetry import trace

from ...core import Agent, Session
from ...core.model import AgentReply, AgentRequest
from ...framework.openai.openai import OpenAIRealtimeRunner, OpenAIRunner
from ..base import RealtimeCallSpan, TracedRealtimeRunner
from ..otel import OTelRealtimeCallSpan


class LogfireOpenAIRunner(OpenAIRunner):

    def __init__(self):
        """
        Initializes a LogfireOpenAIRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.logfire.openai")

        logfire.instrument_openai_agents()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the OpenAI agent with provided multi modal inputs.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with logfire.span("Agent Kernel OpenAI", session_id=session.id) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute("input", result.prompt)
            span.set_attribute("output", str(result))
        return result


class LogfireOpenAIRealtimeRunner(TracedRealtimeRunner, OpenAIRealtimeRunner):
    """
    The OpenAI realtime runner with one Logfire span over each call, tagged with the session id as this provider's ``run()`` span is.
    """

    SPAN_NAME = "Agent Kernel OpenAI realtime"

    def _start_call_span(self, session: Session, agent: Agent) -> RealtimeCallSpan:
        return OTelRealtimeCallSpan(trace.get_tracer("agentkernel.trace.logfire"), self.SPAN_NAME, {"session_id": session.id})
