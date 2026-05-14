import logging
from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.smolagents.smolagents import SmolagentsRunner
from .openllmetry import TraceloopContext


class OpenLLMetrySmolagentsRunner(SmolagentsRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetrySmolagentsRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.smolagents")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Smolagents agent with provided inputs.
        :param agent: The Smolagents agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with TraceloopContext(app_name="AgentKernel Smolagents", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result
