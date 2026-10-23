"""Tests for the Microsoft Agent Framework traced runners (trace/<backend>/maf.py).

Each runner wraps `MAFRunner.run` in its backend's span or context. The framework call is patched, so these check the
tracing wrapper only: the span is opened with the session id, records the reply's prompt and output, and returns the
reply unchanged. The CloudWatch runner is covered with the other CloudWatch runners in test_trace_cloudwatch.py.
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("agent_framework")

from agentkernel.core.base import Session
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.framework.maf.maf import MAFRunner


def _span():
    span = MagicMock(name="span")
    span.__enter__.return_value = span
    span.__exit__.return_value = False
    return span


async def _run(runner):
    return await runner.run(MagicMock(), Session("s1"), [AgentRequestText(prompt="q")])


@pytest.fixture
def fake_logfire(monkeypatch):
    """The `logfire` SDK is not a test dependency: inject a fake module and import the AK runner against it."""
    span = _span()
    fake = types.ModuleType("logfire")
    fake.span = MagicMock(return_value=span)
    fake.span_cm = span
    monkeypatch.setitem(sys.modules, "logfire", fake)
    monkeypatch.delitem(sys.modules, "agentkernel.trace.logfire.maf", raising=False)
    yield fake
    sys.modules.pop("agentkernel.trace.logfire.maf", None)


@pytest.mark.asyncio
async def test_logfire_runner_wraps_the_run_in_a_session_span(fake_logfire):
    from agentkernel.trace.logfire.maf import LogfireMAFRunner

    reply = AgentReplyText(response="hi", prompt="q")
    with patch.object(MAFRunner, "run", AsyncMock(return_value=reply)):
        result = await _run(LogfireMAFRunner())

    assert result is reply
    assert fake_logfire.span.call_args.args == ("Agent Kernel MAF",)
    assert fake_logfire.span.call_args.kwargs["session_id"] == "s1"
    fake_logfire.span_cm.set_attribute.assert_any_call("input", "q")
    fake_logfire.span_cm.set_attribute.assert_any_call("output", "hi")


@pytest.mark.asyncio
async def test_logfire_runner_propagates_the_error_through_the_span(fake_logfire):
    from agentkernel.trace.logfire.maf import LogfireMAFRunner

    with patch.object(MAFRunner, "run", AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await _run(LogfireMAFRunner())

    assert fake_logfire.span_cm.__exit__.call_args[0][0] is RuntimeError


@pytest.mark.asyncio
async def test_langfuse_runner_wraps_the_run_in_a_session_observation():
    pytest.importorskip("langfuse")
    import agentkernel.trace.langfuse.maf as langfuse_maf

    span = _span()
    client = MagicMock()
    client.start_as_current_observation.return_value = span
    reply = AgentReplyText(response="hi", prompt="q")

    with (
        patch.object(langfuse_maf, "propagate_attributes", return_value=_span()) as propagate,
        patch.object(MAFRunner, "run", AsyncMock(return_value=reply)),
    ):
        result = await _run(langfuse_maf.LangFuseMAFRunner(client))

    assert result is reply
    propagate.assert_called_once_with(session_id="s1", tags=["agentkernel"])
    client.start_as_current_observation.assert_called_once_with(name="Agent Kernel MAF", as_type="span")
    span.update.assert_called_once_with(input="q", output="hi")


@pytest.mark.asyncio
async def test_openllmetry_runner_runs_inside_a_traceloop_context():
    pytest.importorskip("traceloop")
    import agentkernel.trace.openllmetry.maf as openllmetry_maf

    reply = AgentReplyText(response="hi", prompt="q")
    with (
        patch.object(openllmetry_maf, "TraceloopContext", return_value=_span()) as context,
        patch.object(MAFRunner, "run", AsyncMock(return_value=reply)),
    ):
        result = await _run(openllmetry_maf.OpenLLMetryMAFRunner())

    assert result is reply
    context.assert_called_once_with(app_name="AgentKernel MAF", association_properties={"session_id": "s1"})
    context.return_value.__exit__.assert_called_once()
