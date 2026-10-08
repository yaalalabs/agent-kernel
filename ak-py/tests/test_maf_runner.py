import base64
import copy
import inspect
from unittest.mock import AsyncMock

import pytest
from agent_framework import (
    Agent,
    AgentResponse,
    AgentResponseUpdate,
    AgentSession,
    Content,
    Message,
)
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from agentkernel.core.model import (
    AgentReplyAny,
    AgentReplyText,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)
from agentkernel.framework.maf.maf import MAFAgent, MAFModule, MAFRunner, MAFSession, MAFToolBuilder


class NativeMockAgent:
    def __init__(self, name="test-agent"):
        self.name = name
        self.default_options = {"instructions": "Test system message", "tools": []}
        self.run = AsyncMock()


@pytest.fixture
def session():
    return Session("test-session")


@pytest.fixture
def runner():
    return MAFRunner()


@pytest.fixture
def native_agent():
    return NativeMockAgent()


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
    valid_b64 = base64.b64encode(b"test_data").decode("utf-8")
    requests = [
        AgentRequestText(prompt="Hello"),
        AgentRequestImage(image_data=valid_b64, name="my_image.png", mime_type="image/png"),
        AgentRequestFile(file_data=valid_b64, name="my_file.pdf", mime_type="application/octet-stream"),
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
    native_response = AgentResponse(messages=[Message(role="assistant", contents=[Content.from_text("Hello from MAF")])])
    native_agent.run.return_value = native_response

    requests = [AgentRequestText(prompt="Hello")]
    reply = await runner.run(maf_agent, session, requests)

    assert isinstance(reply, AgentReplyText)
    assert reply.response == "Hello from MAF"
    assert reply.prompt == "Hello"


@pytest.mark.asyncio
async def test_run_structured_output_dict(runner, session, maf_agent, native_agent):
    native_response = AgentResponse(messages=[], value={"key": "value"})
    native_agent.run.return_value = native_response

    requests = [AgentRequestText(prompt="Hello")]
    reply = await runner.run(maf_agent, session, requests)

    assert isinstance(reply, AgentReplyAny)
    assert reply.content == {"key": "value"}


@pytest.mark.asyncio
async def test_run_structured_output_pydantic(runner, session, maf_agent, native_agent):
    class MyModel(BaseModel):
        key: str

    native_response = AgentResponse(messages=[], value=MyModel(key="value"))
    native_agent.run.return_value = native_response

    requests = [AgentRequestText(prompt="Hello")]
    reply = await runner.run(maf_agent, session, requests)

    assert isinstance(reply, AgentReplyAny)
    assert reply.content == {"key": "value"}


@pytest.mark.asyncio
async def test_run_failure_converts_to_agent_reply_text(runner, session, maf_agent, native_agent):
    native_agent.run.side_effect = ValueError("Some native error")

    requests = [AgentRequestText(prompt="Hello")]
    reply = await runner.run(maf_agent, session, requests)

    assert isinstance(reply, AgentReplyText)
    assert "Some native error" in reply.response


@pytest.mark.asyncio
async def test_stream_success_multi_message(runner, session, maf_agent, native_agent):
    async def mock_stream():
        # Msg 1
        yield AgentResponseUpdate(message_id="msg1", contents=[Content(type="text", text="Hello")])
        yield AgentResponseUpdate(message_id="msg1", contents=[Content(type="text", text=" world")])

        # Tool Call
        yield AgentResponseUpdate(
            message_id=None, contents=[Content(type="function_call", call_id="call1", name="get_weather", arguments='{"city": "NYC"}')]
        )
        yield AgentResponseUpdate(message_id=None, contents=[Content(type="function_result", call_id="call1", result="72F")])

        # Msg 2 (New native ID)
        yield AgentResponseUpdate(message_id="msg2", contents=[Content(type="text", text="It is ")])
        yield AgentResponseUpdate(message_id="msg2", contents=[Content(type="text", text="72F")])

    native_agent.run.return_value = mock_stream()

    requests = [AgentRequestText(prompt="Hello")]
    events = [e async for e in runner.stream(maf_agent, session, requests)]

    msg_starts = [e for e in events if isinstance(e, MessageStart)]
    msg_ends = [e for e in events if isinstance(e, MessageEnd)]

    assert len(msg_starts) == 2
    assert len(msg_ends) == 2

    assert msg_starts[0].message_id == "msg1"
    assert msg_ends[0].message_id == "msg1"

    assert msg_starts[1].message_id == "msg2"
    assert msg_ends[1].message_id == "msg2"
    assert [type(event) for event in events] == [
        MessageStart,
        TextDelta,
        TextDelta,
        ToolCallStart,
        ToolCallArgs,
        ToolCallEnd,
        ToolCallResult,
        MessageEnd,
        MessageStart,
        TextDelta,
        TextDelta,
        MessageEnd,
    ]
    tool_events = [event for event in events if isinstance(event, (ToolCallStart, ToolCallArgs, ToolCallEnd, ToolCallResult))]
    assert all(event.tool_call_id == "call1" for event in tool_events)


@pytest.mark.asyncio
async def test_stream_reasoning_and_missing_ids(runner, session, maf_agent, native_agent):
    async def mock_stream():
        yield AgentResponseUpdate(message_id=None, contents=[Content(type="text_reasoning", text="Thinking...")])
        yield AgentResponseUpdate(message_id=None, contents=[Content(type="text_reasoning", text=" more")])
        yield AgentResponseUpdate(message_id=None, contents=[Content(type="text", text="Here is the answer.")])

    native_agent.run.return_value = mock_stream()
    events = [e async for e in runner.stream(maf_agent, session, [AgentRequestText(prompt="Hello")])]

    r_starts = [e for e in events if isinstance(e, ReasoningStart)]
    r_ends = [e for e in events if isinstance(e, ReasoningEnd)]
    m_starts = [e for e in events if isinstance(e, MessageStart)]
    m_ends = [e for e in events if isinstance(e, MessageEnd)]

    assert len(r_starts) == 1
    assert len(r_ends) == 1
    assert len(m_starts) == 1
    assert len(m_ends) == 1

    assert r_starts[0].message_id == m_starts[0].message_id
    assert r_ends[0].message_id == m_ends[0].message_id


@pytest.mark.asyncio
async def test_stream_missing_id_split(runner, session, maf_agent, native_agent):
    # tests P2 fix: msg1 -> None -> msg1
    async def mock_stream():
        yield AgentResponseUpdate(message_id="msg1", contents=[Content(type="text", text="A")])
        yield AgentResponseUpdate(message_id=None, contents=[Content(type="text", text="B")])
        yield AgentResponseUpdate(message_id="msg1", contents=[Content(type="text", text="C")])

    native_agent.run.return_value = mock_stream()
    events = [e async for e in runner.stream(maf_agent, session, [AgentRequestText(prompt="Hello")])]

    m_starts = [e for e in events if isinstance(e, MessageStart)]
    m_ends = [e for e in events if isinstance(e, MessageEnd)]
    assert len(m_starts) == 1, "Should not split message on missing IDs"
    assert len(m_ends) == 1, "Should not split message on missing IDs"


@pytest.mark.asyncio
async def test_stream_failure_propagates(runner, session, maf_agent, native_agent):
    session.set_framework_context({"cart": ["milk"]})
    old_state = AgentSession(session_id=session.id).to_dict()
    runner._session(session).set_state(old_state)
    error = ValueError("Stream interrupted")

    async def mock_stream():
        native_session = native_agent.run.call_args.kwargs["session"]
        native_session.state["ak_context"]["cart"].append("eggs")
        yield AgentResponseUpdate(message_id="msg1", contents=[Content(type="text", text="Hello")])
        raise error

    native_agent.run.return_value = mock_stream()

    with pytest.raises(ValueError, match="Stream interrupted") as exc:
        async for _ in runner.stream(maf_agent, session, [AgentRequestText(prompt="Hello")]):
            pass
    assert exc.value is error
    assert session.get_framework_context() == {"cart": ["milk"]}
    assert runner._session(session).get_state() == old_state


@pytest.mark.asyncio
async def test_history_preservation_and_clearing(runner, session, maf_agent, native_agent):
    assistant_message = Message(role="assistant", contents=[Content.from_text("Hello")])

    async def native_run(messages, *, session):
        history = session.state.setdefault("messages", [])
        if messages.text == "Hello again":
            # A new empty session with the same ID must not pass this test.
            assert [(message.role, message.text) for message in history] == [("user", "Hi"), ("assistant", "Hello")]
        history.extend([Message(role="user", contents=[Content.from_text(messages.text)]), assistant_message])
        return AgentResponse(messages=[assistant_message])

    native_agent.run.side_effect = native_run

    # first run
    first_reply = await runner.run(maf_agent, session, [AgentRequestText(prompt="Hi")])
    assert first_reply.response == "Hello"
    assert session.get("maf") is not None
    native_session = session.get("maf")
    assert isinstance(native_session, MAFSession)

    # second run
    second_reply = await runner.run(maf_agent, session, [AgentRequestText(prompt="Hello again")])
    assert second_reply.response == "Hello"
    assert native_agent.run.call_count == 2
    # Verify the native_session was passed into the second run
    _, kwargs = native_agent.run.call_args
    assert kwargs.get("session").session_id == session.id
    restored = AgentSession.from_dict(native_session.get_state())
    assert [message.text for message in restored.state["messages"]] == ["Hi", "Hello", "Hello again", "Hello"]

    # test clearing
    session.clear()
    assert session.get("maf") is None


@pytest.mark.asyncio
async def test_options_are_forwarded_to_runner_run(runner, session, maf_agent, native_agent):
    native_response = AgentResponse(messages=[])
    native_agent.run.return_value = native_response

    maf_agent.run_options.update({"options": {"temperature": 0.9}})
    declared = copy.deepcopy(maf_agent.run_options)
    resolved = {"options": {"temperature": 0.5, "max_tokens": 100}}
    maf_agent.resolve_run_options = AsyncMock(return_value=resolved)
    requests = [AgentRequestText(prompt="Hi")]
    await runner.run(maf_agent, session, requests)

    assert native_agent.run.called
    args, kwargs = native_agent.run.call_args
    inspect.signature(Agent.run).bind(native_agent, *args, **kwargs)
    assert kwargs["options"] == resolved["options"]
    maf_agent.resolve_run_options.assert_awaited_once_with(session, requests)
    assert maf_agent.run_options == declared


@pytest.mark.asyncio
async def test_options_are_forwarded_to_runner_stream(runner, session, maf_agent, native_agent):
    async def mock_stream():
        yield AgentResponseUpdate(message_id="msg1", contents=[Content.from_text("Hello")])

    native_agent.run.return_value = mock_stream()
    resolved = {"options": {"temperature": 0.5, "max_tokens": 100}}
    maf_agent.resolve_run_options = AsyncMock(return_value=resolved)
    requests = [AgentRequestText(prompt="Hi")]
    events = [event async for event in runner.stream(maf_agent, session, requests)]

    args, kwargs = native_agent.run.call_args
    inspect.signature(Agent.run).bind(native_agent, *args, **kwargs)
    assert kwargs["options"] == resolved["options"]
    assert kwargs["stream"] is True
    maf_agent.resolve_run_options.assert_awaited_once_with(session, requests)
    assert [event.type for event in events] == ["message_start", "text_delta", "message_end"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_ak_session_wins_without_mutating_declared_options(runner, session, maf_agent, native_agent, stream):
    declared = {"session": AgentSession(session_id="caller-session"), "options": {"temperature": 0.5}}
    maf_agent.run_options.update(declared)

    async def mock_stream():
        yield AgentResponseUpdate(message_id="msg1", contents=[Content.from_text("Hello")])

    for _ in range(2):
        if stream:
            native_agent.run.return_value = mock_stream()
            _ = [event async for event in runner.stream(maf_agent, session, [AgentRequestText(prompt="Hi")])]
        else:
            native_agent.run.return_value = AgentResponse(messages=[])
            await runner.run(maf_agent, session, [AgentRequestText(prompt="Hi")])
        assert native_agent.run.call_args.kwargs["session"].session_id == session.id
        assert maf_agent.run_options == declared


@pytest.mark.parametrize("key", ["messages", "session", "stream"])
def test_reserved_run_options_are_rejected_by_module(key):
    native = NativeMockAgent(name="reserved-options-agent")
    module = MAFModule([native])
    try:
        with pytest.raises(ValueError, match=key):
            module.run_options(native, **{key: object()})
    finally:
        module.unload()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_declared_options_factory_runs_each_turn(session, stream):
    native = NativeMockAgent(name="factory-options-agent")
    module = MAFModule([native])
    calls = []

    def options_factory(agent, current_session, requests):
        calls.append((agent, current_session, requests))
        return {"options": {"temperature": 0.1 * len(calls)}}

    async def mock_stream():
        yield AgentResponseUpdate(message_id="msg1", contents=[Content.from_text("Hello")])

    try:
        module.run_options(native, options_factory, options={"temperature": 0.9})
        wrapped = module.get_agent(native.name)
        requests = [AgentRequestText(prompt="Hi")]
        for turn in range(1, 3):
            if stream:
                native.run.return_value = mock_stream()
                _ = [event async for event in module.runner.stream(wrapped, session, requests)]
            else:
                native.run.return_value = AgentResponse(messages=[])
                await module.runner.run(wrapped, session, requests)
            assert len(calls) == turn
            assert calls[-1] == (wrapped, session, requests)
            assert native.run.call_args.kwargs["options"] == {"temperature": 0.1 * turn}
            assert wrapped.run_options == {"options": {"temperature": 0.9}}
    finally:
        module.unload()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_framework_context_round_trips_with_new_keys(runner, session, maf_agent, native_agent, stream):
    initial_context = {"cart": ["milk"], "user_id": "customer-123"}
    session.set_framework_context(initial_context)

    async def mock_stream():
        yield AgentResponseUpdate(message_id="msg1", contents=[Content.from_text("Added eggs")])

    async def native_run(messages, *, session, stream=False):
        context = session.state["ak_context"]
        context["cart"].append("eggs")
        context["delivery_note"] = "front door"
        if stream:
            return mock_stream()
        return AgentResponse(messages=[Message(role="assistant", contents=[Content.from_text("Added eggs")])])

    native_agent.run.side_effect = native_run
    requests = [AgentRequestText(prompt="Add eggs")]
    if stream:
        _ = [event async for event in runner.stream(maf_agent, session, requests)]
    else:
        reply = await runner.run(maf_agent, session, requests)
        assert reply.response == "Added eggs"

    expected = {"cart": ["milk", "eggs"], "user_id": "customer-123", "delivery_note": "front door"}
    assert session.get_framework_context() == expected
    assert initial_context == {"cart": ["milk"], "user_id": "customer-123"}
    # AK persists the context as the framework context; the MAF snapshot must not carry a second copy.
    restored = AgentSession.from_dict(runner._session(session).get_state())
    assert "ak_context" not in restored.state


@pytest.mark.asyncio
async def test_tool_only_stream_has_no_text_boundaries(runner, session, maf_agent, native_agent):
    async def mock_stream():
        yield AgentResponseUpdate(contents=[Content(type="function_call", call_id="call1", name="weather", arguments='{"city":"Paris"}')])
        yield AgentResponseUpdate(contents=[Content.from_function_result(call_id="call1", result="72F")])

    native_agent.run.return_value = mock_stream()
    events = [event async for event in runner.stream(maf_agent, session, [AgentRequestText(prompt="Weather?")])]
    assert [type(event) for event in events] == [ToolCallStart, ToolCallArgs, ToolCallEnd, ToolCallResult]
    assert all(event.tool_call_id == "call1" for event in events)


@pytest.mark.asyncio
async def test_reasoning_only_stream_has_no_text_boundaries(runner, session, maf_agent, native_agent):
    async def mock_stream():
        yield AgentResponseUpdate(contents=[Content(type="text_reasoning", text="Thinking")])
        yield AgentResponseUpdate(contents=[Content(type="text_reasoning", text=" more")])

    native_agent.run.return_value = mock_stream()
    events = [event async for event in runner.stream(maf_agent, session, [AgentRequestText(prompt="Think")])]
    assert [type(event) for event in events] == [ReasoningStart, ReasoningDelta, ReasoningDelta, ReasoningEnd]
    assert len({event.message_id for event in events}) == 1


def test_module_unnamed_agent_raises(runner):
    unnamed_agent = NativeMockAgent(name=None)
    module = MAFModule(agents=[])

    with pytest.raises(ValueError, match="MAF agents passed to MAFModule must have an explicit name"):
        module.load([unnamed_agent])


def test_module_valid_agent(runner):
    named_agent = NativeMockAgent(name="test")
    module = MAFModule(agents=[named_agent])
    # agents property on Module returns the list of Agent objects
    assert len(module.agents) == 1
    assert module.agents[0].name == "test"


def test_maf_agent_methods(maf_agent):
    assert maf_agent.get_description() == "Test system message"

    maf_agent.override_system_prompt("Additional prompt")
    assert maf_agent.agent.default_options["instructions"] == "Test system message\nAdditional prompt"

    def dummy_tool():
        pass

    maf_agent.attach_tool(dummy_tool)
    assert len(maf_agent.agent.default_options["tools"]) == 1


@pytest.mark.asyncio
async def test_snapshot_validation_preserves_old_state(runner, session, maf_agent, native_agent):
    old_state = AgentSession(session_id=session.id).to_dict()
    session.set("maf", MAFSession())
    session.get("maf").set_state(old_state)
    session.set_framework_context({"safe": 1})

    native_response = AgentResponse(messages=[Message(role="assistant", contents=[Content.from_text("Hello")])])
    native_agent.run.return_value = native_response

    class Unserializable:
        pass

    def side_effect(*args, **kwargs):
        kwargs["session"].state["ak_context"] = {"bad": Unserializable()}
        return native_response

    native_agent.run.side_effect = side_effect

    reply = await runner.run(maf_agent, session, [AgentRequestText(prompt="Hi")])
    assert isinstance(reply, AgentReplyText)
    assert "not picklable" in reply.response or "not JSON serializable" in reply.response

    assert session.get("maf").get_state() == old_state
    assert session.get_framework_context() == {"safe": 1}
    assert native_agent.run.called


@pytest.mark.asyncio
async def test_run_sends_text_and_attachments_as_one_user_message(runner, session, maf_agent, native_agent):
    native_agent.run.return_value = AgentResponse(messages=[Message(role="assistant", contents=[Content.from_text("A cat")])])
    valid_b64 = base64.b64encode(b"test_data").decode("utf-8")
    requests = [
        AgentRequestText(prompt="What is in this image?"),
        AgentRequestImage(image_data=valid_b64, name="cat.png", mime_type="image/png"),
    ]

    await runner.run(maf_agent, session, requests)

    (message,), _ = native_agent.run.call_args
    assert isinstance(message, Message)
    assert message.role == "user"
    assert [content.type for content in message.contents] == ["text", "data"]


@pytest.mark.asyncio
async def test_process_requests_prompt_has_no_leading_newline_and_requires_mime_type(runner):
    valid_b64 = base64.b64encode(b"test_data").decode("utf-8")
    prompt, _ = runner._process_requests([AgentRequestImage(image_data=valid_b64, name="a.png", mime_type="image/png")])
    assert prompt == "[Image attached: a.png]"

    with pytest.raises(ValueError, match="MIME type is required for raw file data"):
        runner._process_requests([AgentRequestFile(file_data=valid_b64, name="a.bin")])


@pytest.mark.asyncio
async def test_stream_correlates_chunked_tool_calls_without_ids(runner, session, maf_agent, native_agent):
    # Chat Completions-style clients send the call id and name on the first chunk only; later argument chunks
    # carry an empty id and the tool_call_index, and parallel calls interleave.
    def chunk(call_id, name, arguments, index):
        content = Content.from_function_call(call_id=call_id, name=name, arguments=arguments)
        content.additional_properties["tool_call_index"] = index
        return AgentResponseUpdate(contents=[content])

    async def mock_stream():
        yield chunk("call_a", "get_weather", '{"ci', 0)
        yield chunk("call_b", "get_time", '{"tz', 1)
        yield chunk("", "", 'ty": "NYC"}', 0)
        yield chunk("", "", '": "UTC"}', 1)
        yield AgentResponseUpdate(contents=[Content.from_function_result(call_id="call_a", result={"temp": 72})])
        yield AgentResponseUpdate(contents=[Content.from_function_result(call_id="call_b", result="12:00")])

    native_agent.run.return_value = mock_stream()
    events = [e async for e in runner.stream(maf_agent, session, [AgentRequestText(prompt="Hello")])]

    starts = [e for e in events if isinstance(e, ToolCallStart)]
    assert [(e.tool_call_id, e.name) for e in starts] == [("call_a", "get_weather"), ("call_b", "get_time")]
    args = {}
    for e in events:
        if isinstance(e, ToolCallArgs):
            args[e.tool_call_id] = args.get(e.tool_call_id, "") + e.delta
    assert args == {"call_a": '{"city": "NYC"}', "call_b": '{"tz": "UTC"}'}
    assert [e.tool_call_id for e in events if isinstance(e, ToolCallEnd)] == ["call_a", "call_b"]
    results = {e.tool_call_id: e.content for e in events if isinstance(e, ToolCallResult)}
    assert results == {"call_a": '{"temp": 72}', "call_b": "12:00"}


def test_override_system_prompt_is_idempotent(maf_agent):
    maf_agent.override_system_prompt("Extra guidance")
    maf_agent.override_system_prompt("Extra guidance")
    assert maf_agent.agent.default_options["instructions"] == "Test system message\nExtra guidance"


def test_attach_tool_skips_duplicate_names(maf_agent, caplog):
    def lookup(city: str) -> str:
        """Look up a city."""
        return city

    maf_agent.attach_tool(lookup)
    maf_agent.attach_tool(lookup)  # same function again: skipped silently
    assert [t.name for t in maf_agent.agent.default_options["tools"]] == ["lookup"]
    assert "already has a tool named" not in caplog.text

    def other_lookup(city: str) -> str:
        """A different function under the same name."""
        return city

    other_lookup.__name__ = "lookup"
    with caplog.at_level("WARNING", logger="ak.maf.runner"):
        maf_agent.attach_tool(other_lookup)
    assert [t.name for t in maf_agent.agent.default_options["tools"]] == ["lookup"]
    assert "already has a tool named 'lookup'" in caplog.text
