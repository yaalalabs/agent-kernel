"""Langfuse runners flush the client after every run on AWS Lambda, through LangFuse.flush_on_lambda.

Each of the six runners carries its own ``finally``, so every one is tested. Runners are built with
``object.__new__`` so their constructors don't install framework instrumentation globally; ``run`` needs only
the client and the parent runner's ``run``, which is patched.
"""

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("langfuse")

from agentkernel.core import Session
from agentkernel.core.model import AgentRequestText
from agentkernel.trace.langfuse.langfuse import LangFuse

_RUNNERS = [
    ("openai", "LangFuseOpenAIRunner"),
    ("langgraph", "LangFuseLangGraph"),
    ("crewai", "LangFuseCrewAIRunner"),
    ("adk", "LangFuseADKRunner"),
    ("smolagents", "LangFuseSmolagentsRunner"),
    ("pydanticai", "LangFusePydanticAIRunner"),
]


@contextlib.contextmanager
def _noop_cm(*args, **kwargs):
    yield


@pytest.fixture(params=_RUNNERS, ids=[module for module, _ in _RUNNERS])
def traced(request, monkeypatch):
    """(runner, client, parent runner class, flush spy) for one Langfuse runner, with its framework extra installed."""
    module_name, class_name = request.param
    module = pytest.importorskip(f"agentkernel.trace.langfuse.{module_name}")
    runner_class = getattr(module, class_name)
    monkeypatch.setattr(module, "propagate_attributes", _noop_cm)
    flush = MagicMock()
    monkeypatch.setattr(LangFuse, "flush_on_lambda", flush)
    client = MagicMock()
    runner = object.__new__(runner_class)
    runner._client = client
    return runner, client, runner_class.__mro__[1], flush


class TestRunnersFlush:
    @pytest.mark.asyncio
    async def test_flushes_after_a_successful_run(self, traced, monkeypatch):
        runner, client, parent, flush = traced
        reply = MagicMock()
        monkeypatch.setattr(parent, "run", AsyncMock(return_value=reply))

        result = await runner.run(MagicMock(), Session("s"), [AgentRequestText(prompt="hi")])

        assert result is reply
        flush.assert_called_once_with(client)

    @pytest.mark.asyncio
    async def test_flushes_after_a_failed_run_and_keeps_the_error(self, traced, monkeypatch):
        runner, client, parent, flush = traced
        monkeypatch.setattr(parent, "run", AsyncMock(side_effect=RuntimeError("boom")))

        with pytest.raises(RuntimeError, match="boom"):
            await runner.run(MagicMock(), Session("s"), [AgentRequestText(prompt="hi")])

        flush.assert_called_once_with(client)


class TestFlushOnLambda:
    def test_flushes_on_lambda(self, monkeypatch):
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "agent")
        client = MagicMock()

        LangFuse.flush_on_lambda(client)

        client.flush.assert_called_once_with()

    def test_does_not_flush_off_lambda(self, monkeypatch):
        monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
        client = MagicMock()

        LangFuse.flush_on_lambda(client)

        client.flush.assert_not_called()

    def test_a_failing_flush_is_logged_not_raised(self, monkeypatch, caplog):
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "agent")
        client = MagicMock()
        client.flush.side_effect = RuntimeError("exporter down")

        LangFuse.flush_on_lambda(client)

        assert "Flushing Langfuse spans after the run failed" in caplog.text
