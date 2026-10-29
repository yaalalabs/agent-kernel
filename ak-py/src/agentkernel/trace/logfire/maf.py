from typing import Any

import logfire

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.maf.maf import MAFRunner


class LogfireMAFRunner(MAFRunner):

    def __init__(self):
        """
        Initializes a LogfireMAFRunner instance.
        """
        super().__init__()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the MAF agent in a Logfire span associated with the session, recording the reply's prompt and output.
        Returns the base runner's reply unchanged. Errors from tracing and the base runner's pause guard propagate.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        :raises ValueError: If this runner has an unanswered paused run in the session.
        """
        with logfire.span("Agent Kernel MAF", session_id=session.id) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute("input", result.prompt)
            span.set_attribute("output", str(result))
        return result
