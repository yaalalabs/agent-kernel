import logging
from typing import Any

from langfuse import Langfuse, get_client, propagate_attributes
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

from ...core import Agent, Session
from ...core.model import AgentReply, AgentRequest
from ...framework.openai.openai import OpenAIRealtimeRunner, OpenAIRunner
from ..base import RealtimeCallSpan, TracedRealtimeRunner
from .langfuse import LangFuse, LangFuseRealtimeCallSpan


class LangFuseOpenAIRunner(OpenAIRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFuseOpenAIRunner instance.
        :param client: The Langfuse client instance.
        """
        super().__init__()
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.openai")

        OpenAIAgentsInstrumentor().instrument()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the OpenAI agent with provided multi modal inputs.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        try:
            with propagate_attributes(session_id=session.id, tags=["agentkernel"]):

                with self._client.start_as_current_observation(name="Agent Kernel OpenAI", as_type="span") as span:

                    result = await super().run(agent, session, requests)
                    span.update(input=result.prompt, output=str(result))
        finally:
            LangFuse.flush_on_lambda(self._client)

        return result


class LangFuseOpenAIRealtimeRunner(TracedRealtimeRunner, OpenAIRealtimeRunner):
    """
    The OpenAI realtime runner with one LangFuse span over each call, tagged with the session id as this provider's ``run()`` span is.
    """

    SPAN_NAME = "Agent Kernel OpenAI realtime"

    def _start_call_span(self, session: Session, agent: Agent) -> RealtimeCallSpan:
        return LangFuseRealtimeCallSpan(get_client(), self.SPAN_NAME, session.id)
