import logging
from typing import Any

from openinference.instrumentation.google_adk import GoogleADKInstrumentor

from ...core import Agent, Session
from ...core.model import AgentReply, AgentRequest
from ...framework.adk.adk import GoogleADKRealtimeRunner, GoogleADKRunner
from ..base import RealtimeCallSpan, TracedRealtimeRunner
from .cloudwatch import INPUT_VALUE, OUTPUT_VALUE, CloudWatch, CloudWatchRealtimeCallSpan


class CloudWatchADKRunner(GoogleADKRunner):

    def __init__(self, tracer: CloudWatch):
        """
        Initializes a CloudWatchADKRunner instance.
        :param tracer: The CloudWatch tracer that wraps each run in a span.
        """
        super().__init__()
        self._tracer = tracer
        self._log = logging.getLogger("ak.trace.cloudwatch.adk")

        GoogleADKInstrumentor().instrument()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the ADK agent with provided multi modal inputs.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with self._tracer.span("Agent Kernel ADK", session) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute(INPUT_VALUE, result.prompt)
            span.set_attribute(OUTPUT_VALUE, str(result))
        return result


class CloudWatchADKRealtimeRunner(TracedRealtimeRunner, GoogleADKRealtimeRunner):
    """
    The ADK realtime runner with one CloudWatch span over each call, tagged with the session id as this provider's ``run()`` span is.
    """

    SPAN_NAME = "Agent Kernel ADK realtime"

    def _start_call_span(self, session: Session, agent: Agent) -> RealtimeCallSpan:
        return CloudWatchRealtimeCallSpan(self.SPAN_NAME, session.id)
