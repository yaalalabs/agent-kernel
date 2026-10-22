import logging
from typing import Any

import logfire

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.claude.claude import ClaudeRunner


class LogfireClaudeRunner(ClaudeRunner):

    def __init__(self) -> None:
        """
        Initializes a LogfireClaudeRunner instance.

        Logfire instruments `ClaudeSDKClient`, the client this runner uses, and only clients created after
        the call get tool spans, which holds because the runner creates one per run.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.logfire.claude")

        logfire.instrument_claude_agent_sdk()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Claude agent with provided multi modal inputs.
        :param agent: The Claude agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with logfire.span("Agent Kernel Claude", session_id=session.id) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute("input", result.prompt)
            span.set_attribute("output", str(result))
        return result
