import logging
from typing import Any

from langfuse import Langfuse
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

from ...adk.adk import GoogleADKRunner
from ...core import Session


class LangFuseADKRunner(GoogleADKRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFuseADKRunner instance.
        :param client: The Langfuse client instance.
        """
        super().__init__()
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.adk")

        GoogleADKInstrumentor().instrument()

    async def run(self, agent: Any, session: Session, prompt: Any):
        """
        Runs the ADK agent with the provided prompt.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        with self._client.start_as_current_span(name="Agent Kernel ADK") as span:
            result = await super().run(agent=agent, prompt=prompt, session=session)
            span.update_trace(session_id=session.id, input=prompt, output=str(result), tags=["agentkernel"])
        return result
