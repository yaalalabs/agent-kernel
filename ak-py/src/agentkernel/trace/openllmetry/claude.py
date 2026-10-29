import logging
from typing import Any

from opentelemetry import context as context_api
from opentelemetry import trace as trace_api
from opentelemetry.semconv_ai import SpanAttributes
from traceloop.sdk.config import is_content_tracing_enabled

from ...core import Session
from ...core.model import AgentReply, AgentRequest
from ...framework.claude.claude import ClaudeRunner
from .openllmetry import TraceloopContext


class OpenLLMetryClaudeRunner(ClaudeRunner):

    def __init__(self) -> None:
        """
        Initializes an OpenLLMetryClaudeRunner instance.

        OpenLLMetry has no Claude Agent SDK instrumentation, and its Anthropic instrumentation cannot see the
        model calls, which the Claude Code CLI subprocess makes. `TraceloopContext` only attaches the session id to
        whatever spans exist, so each run gets one Agent Kernel span of its own, from the OpenTelemetry tracer
        Traceloop configures.
        """
        super().__init__()
        self._log = logging.getLogger("ak.trace.openllmetry.claude")

    @staticmethod
    def _content_tracing_enabled() -> bool:
        """
        :return: Whether the prompt and reply may be recorded: OpenLLMetry's own switch (`TRACELOOP_TRACE_CONTENT`,
            on by default) or its per-context override, as its instrumentations and decorators read them. The span
            is written by hand rather than by an instrumentation, so the switch is not applied to it for us.
        """
        return is_content_tracing_enabled() or bool(context_api.get_value("override_enable_content_tracing"))

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Claude agent with provided multi modal inputs.
        :param agent: The Claude agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """

        with TraceloopContext(app_name="AgentKernel Claude", association_properties={"session_id": session.id}):
            with trace_api.get_tracer("agentkernel.claude").start_as_current_span(
                "Agent Kernel Claude", attributes={"session_id": session.id}
            ) as span:
                result = await super().run(agent, session, requests)
                if self._content_tracing_enabled():
                    span.set_attribute(SpanAttributes.TRACELOOP_ENTITY_INPUT, result.prompt)
                    span.set_attribute(SpanAttributes.TRACELOOP_ENTITY_OUTPUT, str(result))
        return result
