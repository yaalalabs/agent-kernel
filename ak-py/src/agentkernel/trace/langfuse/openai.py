import logging
from typing import Any

from langfuse import Langfuse
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

from ...core import Session
from ...openai.openai import OpenAIRunner


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

    async def run(self, agent: Any, session: Session, prompt: Any):
        """
        Runs the OpenAI agent with the provided prompt.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        with self._client.start_as_current_span(name=session.id) as span:
            result = await super().run(agent=agent, prompt=prompt, session=session)
            span.update_trace(session_id=session.id, input=prompt, output=result)
        return result
