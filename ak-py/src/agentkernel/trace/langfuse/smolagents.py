import logging
from typing import Any

from langfuse import Langfuse

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.smolagents.smolagents import SmolagentsRunner


class LangFuseSmolagentsRunner(SmolagentsRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFuseSmolagentsRunner instance.
        :param client: The Langfuse client instance.
        """
        super().__init__()
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.smolagents")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Smolagents agent with provided inputs.
        :param agent: The Smolagents agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with self._client.start_as_current_span(name="Agent Kernel Smolagents") as span:
            result = await super().run(agent, session, requests)
            span.update_trace(session_id=session.id, input=result.prompt, output=str(result), tags=["agentkernel"])
        return result
