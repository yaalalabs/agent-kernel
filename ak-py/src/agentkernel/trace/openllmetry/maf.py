from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.maf.maf import MAFRunner
from .openllmetry import TraceloopContext


class OpenLLMetryMAFRunner(MAFRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryMAFRunner instance.
        """
        super().__init__()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the MAF agent in an OpenLLMetry context associated with the session.
        Returns the base runner's reply unchanged. Errors from tracing and the base runner's pause guard propagate.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        :raises ValueError: If this runner has an unanswered paused run in the session.
        """

        with TraceloopContext(app_name="AgentKernel MAF", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result
