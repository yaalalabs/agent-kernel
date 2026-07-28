import logging
from typing import Any

from langfuse import Langfuse, propagate_attributes
from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
from opentelemetry import trace as trace_api
from pydantic_ai import Agent

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.pydanticai.pydanticai import PydanticAIRunner


class LangFusePydanticAIRunner(PydanticAIRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFusePydanticAIRunner instance.
        :param client: The Langfuse client instance.
        """
        super().__init__()
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.pydanticai")
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

        with propagate_attributes(session_id=session.id, tags=["agentkernel"]):

            with self._client.start_as_current_observation(name="Agent Kernel Pydantic AI", as_type="span") as span:

                result = await super().run(agent, session, requests)
                span.update(input=result.prompt, output=str(result))

        return result
