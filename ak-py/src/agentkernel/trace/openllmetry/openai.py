import logging
from typing import Any

from ...core import Session
from ...openai.openai import OpenAIRunner
from .openllmetry import TraceloopContext


class OpenLLMetryOpenAIRunner(OpenAIRunner):

    def __init__(self):
        """
        Initializes an OpenLLMetryOpenAIRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.openai")

    async def run(self, agent: Any, session: Session, prompt: Any):
        """
        Runs the OpenAI agent with the provided prompt.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel OpenAI", association_properties={"session_id": session.id}):
            result = await super().run(agent=agent, prompt=prompt, session=session)
        return result
