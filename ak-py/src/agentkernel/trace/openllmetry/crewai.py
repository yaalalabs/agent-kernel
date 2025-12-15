import logging
from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.crewai.crewai import CrewAIRunner
from .openllmetry import TraceloopContext


class OpenLLMetryCrewAIRunner(CrewAIRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryCrewAIRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.crewai")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the CrewAI agent with provided multi modal inputs.
        :param agent: The CrewAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel CrewAI", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result
