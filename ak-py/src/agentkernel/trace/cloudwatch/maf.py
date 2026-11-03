from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.maf.maf import MAFRunner
from .cloudwatch import INPUT_VALUE, OUTPUT_VALUE, CloudWatch


class CloudWatchMAFRunner(MAFRunner):

    def __init__(self, tracer: CloudWatch):
        """
        Initializes a CloudWatchMAFRunner instance.
        :param tracer: The CloudWatch tracer that wraps each run in a span.
        """
        super().__init__()
        self._tracer = tracer

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the MAF agent in a CloudWatch span with the reply's prompt and output as attributes.
        Returns the base runner's reply unchanged. Errors from tracing and the base runner's pause guard propagate.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        :raises ValueError: If this runner has an unanswered paused run in the session.
        """
        with self._tracer.span("Agent Kernel MAF", session) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute(INPUT_VALUE, result.prompt)
            span.set_attribute(OUTPUT_VALUE, str(result))
        return result
