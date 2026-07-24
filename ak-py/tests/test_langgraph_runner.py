from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.framework.langgraph.langgraph import LangGraphRunner

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


class WeatherResponse(BaseModel):
    city: str
    conditions: str


def _mock_agent(result):
    agent = MagicMock()
    agent._system_prompt = ""
    agent.agent = MagicMock()
    agent.agent.ainvoke = AsyncMock(return_value=result)
    return agent


def _mock_stream_agent(events, state_values):
    """Agent mock whose astream_events yields the given events and aget_state returns state_values."""
    agent = MagicMock()
    agent._system_prompt = ""
    agent.agent = MagicMock()

    async def astream_events(input, config, version):
        for event in events:
            yield event

    agent.agent.astream_events = astream_events
    state = MagicMock()
    state.values = state_values
    agent.agent.aget_state = AsyncMock(return_value=state)
    return agent


def _message(content):
    message = MagicMock()
    message.content = content
    return message


def _chunk(content):
    chunk = MagicMock()
    chunk.content = content
    return chunk


class TestLangGraphRunnerFrameworkContext:
    """framework_context spread into the input state and declared-channel write-back."""

    @pytest.mark.asyncio
    async def test_caller_keys_spread_into_input_and_declared_channels_round_trip(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42", "ephemeral": "x"})
        requests = [AgentRequestText(prompt="hi")]
        # Only 'user_id' is a declared channel that comes back on result; 'ephemeral' is dropped.
        result = {"messages": [_message("hello")], "user_id": "99"}
        agent = _mock_agent(result)

        await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        input_state = kwargs["input"]
        assert input_state["user_id"] == "42"
        assert input_state["ephemeral"] == "x"
        assert "messages" in input_state

        # 'user_id' round-trips from result; 'ephemeral' keeps its seeded value (untouched key preserved).
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "99", "ephemeral": "x"}

    @pytest.mark.asyncio
    async def test_messages_not_overwritten_by_context(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"messages": "EVIL"})
        requests = [AgentRequestText(prompt="hi")]
        result = {"messages": [_message("hello")]}
        agent = _mock_agent(result)

        await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        input_state = kwargs["input"]
        assert input_state["messages"] != "EVIL"
        assert isinstance(input_state["messages"], list)

    @pytest.mark.asyncio
    async def test_absent_key_skips_write_back(self):
        runner = LangGraphRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        result = {"messages": [_message("hello")]}
        agent = _mock_agent(result)

        await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        assert set(kwargs["input"].keys()) == {"messages"}
        assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent({})
        agent.agent.ainvoke = AsyncMock(side_effect=Exception("boom"))

        reply = await runner.run(agent, session, requests)

        assert reply.response.startswith("Error")
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        event = {"event": "on_chat_model_stream", "data": {"chunk": _chunk("tok")}}
        agent = _mock_stream_agent([event], {"user_id": "99"})

        deltas = [delta async for delta in runner.stream(agent, session, requests)]

        assert deltas == ["tok"]
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "99"}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        event = {"event": "on_chat_model_stream", "data": {"chunk": _chunk("tok")}}
        agent = _mock_stream_agent([event], {"user_id": "99"})

        agen = runner.stream(agent, session, requests)
        first = await agen.__anext__()
        assert first == "tok"
        await agen.aclose()  # simulate client disconnect at the yield

        agent.agent.aget_state.assert_not_called()
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42"}


class TestLangGraphRunnerStructuredOutput:
    """Test structured output detection via the structured_response result key"""

    @pytest.mark.asyncio
    async def test_structured_response_model_returns_agent_reply_any(self):
        runner = LangGraphRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="weather in Colombo?")]
        result = {
            "messages": [_message("WeatherResponse(city='Colombo', conditions='sunny')")],
            "structured_response": WeatherResponse(city="Colombo", conditions="sunny"),
        }
        agent = _mock_agent(result)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"city": "Colombo", "conditions": "sunny"}
        assert reply.prompt == "weather in Colombo?"

    @pytest.mark.asyncio
    async def test_structured_response_dict_returns_agent_reply_any(self):
        runner = LangGraphRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="weather?")]
        result = {
            "messages": [_message("...")],
            "structured_response": {"city": "Colombo", "conditions": "sunny"},
        }
        agent = _mock_agent(result)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"city": "Colombo", "conditions": "sunny"}

    @pytest.mark.asyncio
    async def test_without_structured_response_returns_last_message_text(self):
        runner = LangGraphRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]
        result = {"messages": [_message("first"), _message("Hi there!")]}
        agent = _mock_agent(result)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Hi there!"
        assert reply.prompt == "hello"
