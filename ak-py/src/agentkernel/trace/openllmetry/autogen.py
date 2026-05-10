import logging
from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.autogen.autogen import AutogenRunner
from .openllmetry import TraceloopContext


class OpenLLMetryAutogenRunner(AutogenRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryAutogenRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.autogen")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the AutoGen agent with provided inputs.
        :param agent: The AutoGen agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with TraceloopContext(app_name="AgentKernel AutoGen", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result
