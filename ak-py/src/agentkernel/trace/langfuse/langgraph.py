import logging
from typing import Any

from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.langgraph.langgraph import LangGraphRunner


class LangFuseLangGraph(LangGraphRunner):

    def __init__(self, client: Langfuse):
        """
        Initializes a LangFuseLangGraph instance.
        :param client: The Langfuse client instance.
        """
        super().__init__()
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.langgraph")
        self._callback_handler = CallbackHandler()

    def _session_config(self, agent: Any, session: Session) -> dict:
        """
        Wires the Langfuse callback handler into the base runner's session config so LangGraph emits traces.

        Overriding the config seam rather than `_prepare_session_and_messages` keeps message building
        and framework_context handling in the base runner, and covers a **resumed** run too: that path
        builds no messages, so an override on the message-building method missed it entirely — losing
        traces for everything after a human's approval, which is where a gated tool finally runs.

        :param agent: The LangGraph agent.
        :param session: The AgentKernel session.
        :return: The session config with the Langfuse callback wired in.
        """
        config = super()._session_config(agent, session)
        config["callbacks"] = [self._callback_handler]
        return config

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the LangGraph agent inside a Langfuse span, delegating execution to the base runner.
        :param agent: The LangGraph agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with propagate_attributes(session_id=session.id, tags=["agentkernel"]):
            with self._client.start_as_current_observation(name="Agent Kernel LangGraph", as_type="span") as span:
                result = await super().run(agent, session, requests)
                span.update(input=result.prompt, output=str(result))
        return result
