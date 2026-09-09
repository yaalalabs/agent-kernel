"""Regression tests: the Langfuse LangGraph traced runner must not bypass framework_context.

``LangFuseLangGraph.run()`` delegates to ``LangGraphRunner.run()`` and wires the Langfuse callback in
via ``_prepare_session_and_messages``, so the shared base plumbing runs in the traced path too.
"""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("langfuse")

from agentkernel.core import Session
from agentkernel.core.model import AgentRequestText
from agentkernel.trace.langfuse.langgraph import LangFuseLangGraph

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


def _message(content):
    message = MagicMock()
    message.content = content
    return message


def _mock_agent(result):
    agent = MagicMock()
    agent._system_prompt = ""
    agent.agent = MagicMock()
    agent.agent.ainvoke = AsyncMock(return_value=result)
    return agent


@contextlib.contextmanager
def _noop_cm(*args, **kwargs):
    yield


class TestLangFuseLangGraphFrameworkContext:
    """The traced runner routes through the base runner's framework_context plumbing."""

    @pytest.mark.asyncio
    async def test_context_injected_and_written_back_through_traced_runner(self):
        runner = LangFuseLangGraph(client=MagicMock())
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42", "ephemeral": "x"})
        requests = [AgentRequestText(prompt="hi")]
        # Only 'user_id' is a declared channel that comes back on result; 'ephemeral' is dropped.
        result = {"messages": [_message("hello")], "user_id": "99"}
        agent = _mock_agent(result)

        with patch("agentkernel.trace.langfuse.langgraph.propagate_attributes", _noop_cm):
            await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        input_state = kwargs["input"]
        assert input_state["user_id"] == "42"
        assert input_state["ephemeral"] == "x"
        assert "messages" in input_state
        assert kwargs["config"]["callbacks"] == [runner._callback_handler]
        # 'user_id' round-trips from result; 'ephemeral' keeps its seeded value.
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "99", "ephemeral": "x"}

    @pytest.mark.asyncio
    async def test_absent_key_skips_write_back_through_traced_runner(self):
        runner = LangFuseLangGraph(client=MagicMock())
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        result = {"messages": [_message("hello")]}
        agent = _mock_agent(result)

        with patch("agentkernel.trace.langfuse.langgraph.propagate_attributes", _noop_cm):
            await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        assert set(kwargs["input"].keys()) == {"messages"}
        assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact_through_traced_runner(self):
        runner = LangFuseLangGraph(client=MagicMock())
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent({})
        agent.agent.ainvoke = AsyncMock(side_effect=Exception("boom"))

        with patch("agentkernel.trace.langfuse.langgraph.propagate_attributes", _noop_cm):
            reply = await runner.run(agent, session, requests)

        assert reply.response.startswith("Error")
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42"}
