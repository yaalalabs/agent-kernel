import logging
from collections.abc import AsyncGenerator
from typing import Any

from ...core import Session
from ...core.event import StreamEvent
from ...core.model import AgentReply, AgentRequest
from ...framework.maf.maf import MAFRunner
from .openllmetry import TraceloopContext


class OpenLLMetryMAFRunner(MAFRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryMAFRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.maf")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the MAF agent with provided multi modal inputs.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel MAF", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result

    