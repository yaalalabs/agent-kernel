import logging
from typing import Any

from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
from opentelemetry import trace as trace_api
from pydantic_ai import Agent

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.pydanticai.pydanticai import PydanticAIRunner
from .cloudwatch import INPUT_VALUE, OUTPUT_VALUE, CloudWatch


class CloudWatchPydanticAIRunner(PydanticAIRunner):

    def __init__(self, tracer: CloudWatch):
        """
        Initializes a CloudWatchPydanticAIRunner instance.
        :param tracer: The CloudWatch tracer that wraps each run in a span.
        """
        super().__init__()
        self._tracer = tracer
        self._log = logging.getLogger("ak.trace.cloudwatch.pydanticai")

        Agent.instrument_all()
        tracer_provider = trace_api.get_tracer_provider()
        if hasattr(tracer_provider, "add_span_processor"):
            tracer_provider.add_span_processor(OpenInferenceSpanProcessor())
        else:
            self._log.debug("Active TracerProvider does not support add_span_processor; skipping OpenInference span processor")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Pydantic AI agent with provided multi modal inputs.
        :param agent: The Pydantic AI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with self._tracer.span("Agent Kernel Pydantic AI", session) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute(INPUT_VALUE, result.prompt)
            span.set_attribute(OUTPUT_VALUE, str(result))
        return result
