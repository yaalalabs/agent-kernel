import logging
from typing import Any, ClassVar

from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

from ...core import Agent, Session
from ...core.model import AgentReply, AgentRequest
from ...framework.openai.openai import OpenAIRealtimeRunner, OpenAIRunner
from ..base import RealtimeCallSpan, TracedRealtimeRunner, ensure_instrumented
from .cloudwatch import INPUT_VALUE, OUTPUT_VALUE, CloudWatch, CloudWatchRealtimeCallSpan


def instrument_openai() -> None:
    """
    Installs the OpenInference instrumentor the text runner and the realtime runner class both rely on, once.
    """
    ensure_instrumented(OpenAIAgentsInstrumentor())


class CloudWatchOpenAIRunner(OpenAIRunner):

    def __init__(self, tracer: CloudWatch):
        """
        Initializes a CloudWatchOpenAIRunner instance.
        :param tracer: The CloudWatch tracer that wraps each run in a span.
        """
        super().__init__()
        self._tracer = tracer
        self._log = logging.getLogger("ak.trace.cloudwatch.openai")

        instrument_openai()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the OpenAI agent with provided multi modal inputs.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with self._tracer.span("Agent Kernel OpenAI", session) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute(INPUT_VALUE, result.prompt)
            span.set_attribute(OUTPUT_VALUE, str(result))
        return result


class CloudWatchOpenAIRealtimeRunner(TracedRealtimeRunner, OpenAIRealtimeRunner):
    """
    The OpenAI realtime runner with one CloudWatch span over each call, tagged with the session id as this provider's ``run()`` span is.
    """

    # Bound by the provider (``bound_to``), as the text runner is handed the same tracer.
    _cloudwatch: ClassVar[CloudWatch | None] = None
    SPAN_NAME = "Agent Kernel OpenAI realtime"

    def _start_call_span(self, session: Session, agent: Agent) -> RealtimeCallSpan:
        return CloudWatchRealtimeCallSpan(self._cloudwatch._tracer, self.SPAN_NAME, session.id)
