import logging
from typing import Any

from langfuse import Langfuse
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny, AgentRequestText

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
        with self._client.start_as_current_span(name="Agent Kernel OpenAI") as span:
            result = await super().run(agent=agent, prompt=prompt, session=session)
            span.update_trace(session_id=session.id, input=prompt, output=result, tags=["agentkernel"])
        return result

    async def run_multi(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the OpenAI agent with provided multi modal inputs.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        reply = "No valid requests found"
        for req in requests:
            if isinstance(req, AgentRequestAny):  # will not handle this request type in the Agent
                continue
            if isinstance(req, AgentRequestText):
                reply = await self.run(agent, session, req.text)
                break
            else:
                reply = "Sorry. Agent kernel OpenAI runner is unable to handle content other than text at the moment"
                break

        if hasattr(reply, "raw"):
            reply = str(reply.raw)
        else:
            reply = str(reply)

        return AgentReplyText(text=reply)
