import logging
from typing import Any

from ...adk.adk import GoogleADKRunner
from ...core import Session
from .openllmetry import TraceloopContext


class OpenLLMetryADKRunner(GoogleADKRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryADKRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.adk")

    async def run(self, agent: Any, session: Session, prompt: Any):
        """
        Runs the ADK agent with the provided prompt.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel ADK", association_properties={"session_id": session.id}):
            result = await super().run(agent=agent, prompt=prompt, session=session)
        return result
