import logging
from typing import Any

from openinference.instrumentation.claude_agent_sdk import ClaudeAgentSDKInstrumentor

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.claude.claude import ClaudeRunner
from .cloudwatch import INPUT_VALUE, OUTPUT_VALUE, CloudWatch


class CloudWatchClaudeRunner(ClaudeRunner):

    def __init__(self, tracer: CloudWatch):
        """
        Initializes a CloudWatchClaudeRunner instance.

        The model calls run inside the Claude Code CLI subprocess, out of reach of Python-side LLM
        instrumentation, so the SDK's own OpenInference instrumentor supplies the agent and tool spans.
        :param tracer: The CloudWatch tracer that wraps each run in a span.
        """
        super().__init__()
        self._tracer = tracer
        self._log = logging.getLogger("ak.trace.cloudwatch.claude")

        ClaudeAgentSDKInstrumentor().instrument()

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Claude agent with provided multi modal inputs.
        :param agent: The Claude agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        with self._tracer.span("Agent Kernel Claude", session) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute(INPUT_VALUE, result.prompt)
            span.set_attribute(OUTPUT_VALUE, str(result))
        return result
