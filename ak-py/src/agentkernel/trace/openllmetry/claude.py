import logging
from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.claude.claude import ClaudeRunner
from .openllmetry import TraceloopContext


class OpenLLMetryClaudeRunner(ClaudeRunner):

    def __init__(self) -> None:
        """
        Initializes an OpenLLMetryClaudeRunner instance.

        OpenLLMetry has no Claude Agent SDK instrumentation, and its Anthropic instrumentation cannot see the
        model calls, which the Claude Code CLI subprocess makes. Each run gets the outer Agent Kernel span only.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.claude")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Claude agent with provided multi modal inputs.
        :param agent: The Claude agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel Claude", association_properties={"session_id": session.id}):
            result = await super().run(agent, session, requests)
        return result
