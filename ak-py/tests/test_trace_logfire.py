"""Tests for the Logfire trace provider (trace/logfire/).

The `logfire` SDK is not a test dependency, so `fake_logfire` injects a fake module into
`sys.modules` and re-imports the AK logfire package against it.
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText, AgentRequestText


def _purge_ak_logfire_modules():
    for name in [n for n in list(sys.modules) if n.startswith("agentkernel.trace.logfire")]:
        del sys.modules[name]


@pytest.fixture
def fake_logfire(monkeypatch):
    span = MagicMock(name="span")
    span.__enter__.return_value = span
    span.__exit__.return_value = False

    fake = types.ModuleType("logfire")
    fake.configure = MagicMock()
    fake.instrument_openai_agents = MagicMock()
    fake.span = MagicMock(return_value=span)
    fake.span_cm = span  # expose for assertions

    monkeypatch.setitem(sys.modules, "logfire", fake)
    _purge_ak_logfire_modules()  # force fresh import against the fake
    yield fake
    _purge_ak_logfire_modules()  # leave a clean slate for other tests


def _config(type_):
    cfg = MagicMock()
    cfg.trace.enabled = True
    cfg.trace.type = type_
    return cfg


def test_factory_builds_logfire(fake_logfire):
    from agentkernel.trace.logfire.logfire import Logfire
    from agentkernel.trace.trace import Trace

    with patch.object(AKConfig, "get", return_value=_config("logfire")):
        trace = Trace.get()

    assert isinstance(trace._instance, Logfire)
    fake_logfire.configure.assert_called_once()


def test_init_configures_once(fake_logfire):
    from agentkernel.trace.logfire.logfire import Logfire

    tracer = Logfire()
    tracer.init()
    tracer.init()

    fake_logfire.configure.assert_called_once()


@pytest.mark.asyncio
async def test_smolagents_runner_wraps_span_and_sets_io(fake_logfire):
    from agentkernel.framework.smolagents.smolagents import SmolagentsRunner
    from agentkernel.trace.logfire.smolagents import LogfireSmolagentsRunner

    reply = AgentReplyText(response="hi", prompt="q")
    with patch.object(SmolagentsRunner, "run", AsyncMock(return_value=reply)):
        runner = LogfireSmolagentsRunner()
        result = await runner.run(MagicMock(), Session("s1"), [AgentRequestText(prompt="q")])

    assert result is reply
    assert fake_logfire.span.call_args.kwargs["session_id"] == "s1"
    fake_logfire.span_cm.set_attribute.assert_any_call("input", "q")
    fake_logfire.span_cm.set_attribute.assert_any_call("output", "hi")


@pytest.mark.asyncio
async def test_smolagents_runner_propagates_error_to_span(fake_logfire):
    from agentkernel.framework.smolagents.smolagents import SmolagentsRunner
    from agentkernel.trace.logfire.smolagents import LogfireSmolagentsRunner

    with patch.object(SmolagentsRunner, "run", AsyncMock(side_effect=RuntimeError("boom"))):
        runner = LogfireSmolagentsRunner()
        with pytest.raises(RuntimeError):
            await runner.run(MagicMock(), Session("s1"), [AgentRequestText(prompt="q")])

    assert fake_logfire.span_cm.__exit__.call_args[0][0] is RuntimeError


@pytest.mark.asyncio
async def test_openai_runner_activates_instrumentation(fake_logfire):
    from agentkernel.framework.openai.openai import OpenAIRunner
    from agentkernel.trace.logfire.openai import LogfireOpenAIRunner

    reply = AgentReplyText(response="hi", prompt="q")
    with patch.object(OpenAIRunner, "run", AsyncMock(return_value=reply)):
        runner = LogfireOpenAIRunner()
        result = await runner.run(MagicMock(), Session("s1"), [AgentRequestText(prompt="q")])

    fake_logfire.instrument_openai_agents.assert_called_once()
    assert result is reply
    fake_logfire.span.assert_called_once()


def test_all_runners_subclass_their_framework_base(fake_logfire):
    import agentkernel.trace.logfire.adk as adk_mod
    import agentkernel.trace.logfire.crewai as crewai_mod
    from agentkernel.framework.adk.adk import GoogleADKRunner
    from agentkernel.framework.crewai.crewai import CrewAIRunner
    from agentkernel.framework.langgraph.langgraph import LangGraphRunner
    from agentkernel.framework.openai.openai import OpenAIRunner
    from agentkernel.framework.smolagents.smolagents import SmolagentsRunner
    from agentkernel.trace.logfire.adk import LogfireADKRunner
    from agentkernel.trace.logfire.crewai import LogfireCrewAIRunner
    from agentkernel.trace.logfire.langgraph import LogfireLangGraphRunner
    from agentkernel.trace.logfire.openai import LogfireOpenAIRunner
    from agentkernel.trace.logfire.smolagents import LogfireSmolagentsRunner

    assert issubclass(LogfireOpenAIRunner, OpenAIRunner)
    assert issubclass(LogfireLangGraphRunner, LangGraphRunner)
    assert issubclass(LogfireCrewAIRunner, CrewAIRunner)
    assert issubclass(LogfireADKRunner, GoogleADKRunner)
    assert issubclass(LogfireSmolagentsRunner, SmolagentsRunner)

    # crewai/adk activate OpenInference instrumentors in __init__ — patch to avoid global side effects
    with patch.object(crewai_mod, "CrewAIInstrumentor"), patch.object(crewai_mod, "LiteLLMInstrumentor"):
        assert isinstance(LogfireCrewAIRunner(), CrewAIRunner)
    with patch.object(adk_mod, "GoogleADKInstrumentor"):
        assert isinstance(LogfireADKRunner(), GoogleADKRunner)
