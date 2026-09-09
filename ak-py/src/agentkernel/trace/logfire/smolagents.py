import logging
from typing import Any

import logfire

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.smolagents.smolagents import SmolagentsRunner


class LogfireSmolagentsRunner(SmolagentsRunner):

    def __init__(self):
        """
        Initializes a LogfireSmolagentsRunner instance.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.logfire.smolagents")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Smolagents agent with provided inputs.
        :param agent: The Smolagents agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with logfire.span("Agent Kernel Smolagents", session_id=session.id) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute("input", result.prompt)
            span.set_attribute("output", str(result))
        return result
