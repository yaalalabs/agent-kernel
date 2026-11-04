import logging
from typing import Any

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.smolagents.smolagents import SmolagentsRunner
from .cloudwatch import INPUT_VALUE, OUTPUT_VALUE, CloudWatch


class CloudWatchSmolagentsRunner(SmolagentsRunner):

    def __init__(self, tracer: CloudWatch):
        """
        Initializes a CloudWatchSmolagentsRunner instance.
        :param tracer: The CloudWatch tracer that wraps each run in a span.
        """
        super().__init__()
        self._tracer = tracer
        self._log = logging.getLogger("ak.trace.cloudwatch.smolagents")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Smolagents agent with provided inputs.
        :param agent: The Smolagents agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with self._tracer.span("Agent Kernel Smolagents", session) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute(INPUT_VALUE, result.prompt)
            span.set_attribute(OUTPUT_VALUE, str(result))
        return result
