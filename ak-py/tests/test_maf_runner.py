import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentkernel.core import Session, ToolBuilder, ToolContext
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta, ToolCallArgs, ToolCallEnd, ToolCallStart
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestFile, AgentRequestImage, AgentRequestText
from agentkernel.framework.maf.maf import MAFAgent, MAFRunner, MAFToolBuilder


class MockMAFUpdate:
    def __init__(self, text=None, tool_calls=None):
        self.text = text
        self.tool_calls = tool_calls or []


class MockMAFToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.name = name
        self.arguments = arguments


class MockMAFAgentInstance:
    def __init__(self):
        self.name = "test-agent"
        self.instructions = "Test system message"
        self.tools = []
        self.run = AsyncMock()


@pytest.fixture
def session():
    return Session("test-session")


@pytest.fixture
def runner():
    return MAFRunner()


@pytest.fixture
def native_agent():
    return MockMAFAgentInstance()


@pytest.fixture
def maf_agent(runner, native_agent):
    return MAFAgent(name="test-agent", runner=runner, agent=native_agent)


@pytest.mark.asyncio
async def test_process_requests_text_only(runner):
    requests = [AgentRequestText(prompt="Hello")]
    prompt, inputs = runner._process_requests(requests)
    assert inputs == ["Hello"]
    assert prompt == "Hello"


@pytest.mark.asyncio
async def test_process_requests_multi_modal(runner):
    import base64
    valid_b64 = base64.b64encode(b"test_data").decode('utf-8')
    requests = [
        AgentRequestText(prompt="Hello"),
        AgentRequestImage(image_data=valid_b64, name="my_image.png"),
        AgentRequestFile(file_data=valid_b64, name="my_file.pdf"),
    ]
    prompt, inputs = runner._process_requests(requests)
    assert len(inputs) == 3
    assert inputs[0] == "Hello"
    assert getattr(inputs[1], "type") == "data"
    assert getattr(inputs[1], "media_type") == "image/png"
    assert getattr(inputs[2], "type") == "data"
    assert getattr(inputs[2], "media_type") == "application/octet-stream"
    assert "[Image attached: my_image.png]" in prompt


@pytest.mark.asyncio
async def test_run_success(runner, session, maf_agent, native_agent):
    native_agent.run.return_value = MockMAFUpdate(text="Hello from MAF")

    requests = [AgentRequestText(prompt="Hello")]
    reply = await runner.run(maf_agent, session, requests)

    assert isinstance(reply, AgentReplyText)
    assert reply.response == "Hello from MAF"
    assert reply.prompt == "Hello"

    native_agent.run.assert_called_once()
    args, kwargs = native_agent.run.call_args
    assert args[0] == ["Hello"]
    assert "session" in kwargs


@pytest.mark.asyncio
async def test_run_structured_output(runner, session, maf_agent, native_agent):
    # Mocking a JSON string response for structured output
    native_agent.run.return_value = MockMAFUpdate(text='{"key": "value"}')

    requests = [AgentRequestText(prompt="Hello")]
    reply = await runner.run(maf_agent, session, requests)

    # Note: Mock returns simple text update, we check for AgentReplyText
    assert isinstance(reply, AgentReplyText)
    assert reply.response == '{"key": "value"}'


@pytest.mark.asyncio
async def test_stream_success(runner, session, maf_agent, native_agent):
    # Mock an async iterator returned by native_agent.run(stream=True)
    async def mock_stream():
        yield MockMAFUpdate(text="Hello ")
        yield MockMAFUpdate(tool_calls=[MockMAFToolCall(id="call_1", name="get_weather", arguments='{"city": "NYC"}')])
        yield MockMAFUpdate(text="world")

    native_agent.run.return_value = mock_stream()

    requests = [AgentRequestText(prompt="Hello")]
    events = []
    async for event in runner.stream(maf_agent, session, requests):
        events.append(event)

    native_agent.run.assert_called_once()
    args, kwargs = native_agent.run.call_args
    assert kwargs.get("stream") is True

    # Validate event sequence
    assert any(isinstance(e, MessageStart) for e in events)
    assert any(isinstance(e, TextDelta) and e.content == "Hello " for e in events)
    assert any(isinstance(e, ToolCallStart) and e.name == "get_weather" for e in events)
    assert any(isinstance(e, ToolCallArgs) and "NYC" in e.delta for e in events)
    assert any(isinstance(e, ToolCallEnd) for e in events)
    assert any(isinstance(e, TextDelta) and e.content == "world" for e in events)
    assert any(isinstance(e, MessageEnd) for e in events)


def test_maf_agent_methods(maf_agent):
    assert maf_agent.get_description() == "Test system message"

    maf_agent.override_system_prompt("Additional prompt")
    assert maf_agent.agent.instructions == "Test system message\nAdditional prompt"

    def dummy_tool():
        pass

    maf_agent.attach_tool(dummy_tool)
    assert len(maf_agent.agent.tools) == 1
