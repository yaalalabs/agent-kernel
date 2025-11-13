import logging
from typing import Any

from agents import Runner
from langfuse import Langfuse

from ...core import Session
from ...openai.openai import OpenAIRunner
from ..base import BaseRunner


class LangFuseOpenAI(BaseRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFuseOpenAI instance.
        :param client: The Langfuse client instance.
        """
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.openai")
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

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
            result = await Runner.run(agent.agent, prompt, session=OpenAIRunner.session(session))
            span.update_trace(session_id=session.id)
        return result.final_output
