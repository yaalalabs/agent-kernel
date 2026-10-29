import base64
import copy
import inspect
import json
import pickle
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_framework import (
    Agent,
    AgentResponse,
    AgentResponseUpdate,
    AgentSession,
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    Message,
    ResponseStream,
)
from agent_framework import tool as maf_tool
from agent_framework.observability import ChatTelemetryLayer
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    PausedInterruption,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    RunPaused,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyAny,
    AgentReplyText,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
    ResumeDecision,
)
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.framework.maf.maf import MAFAgent, MAFModule, MAFRunner, MAFSession


class NativeMockAgent:
    """Stands in for a MAF `Agent`: the attributes the adapter reads, with an `AsyncMock` run."""

    def __init__(self, name="test-agent"):
        self.name = name
        self.description = None
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


def test_attachment_urls_and_data_uris_map_to_uri_and_data_content(runner):
    raw = base64.b64encode(b"test_data").decode("utf-8")
    requests = [
        AgentRequestImage(image_data="https://example.com/cat.png", name="cat.png", mime_type="image/png"),
        AgentRequestFile(file_data="s3://bucket/report.pdf", name="report.pdf"),
        AgentRequestImage(image_data=f"data:image/jpeg;base64,{raw}", name="inline.jpg"),
    ]

    _, inputs = runner._process_requests(requests)

    url, s3, inline = inputs
    assert (url.type, url.uri, url.media_type) == ("uri", "https://example.com/cat.png", "image/png")
    assert (s3.type, s3.uri) == ("uri", "s3://bucket/report.pdf")
    assert inline.type == "data" and inline.media_type == "image/jpeg"  # the MIME type comes from the data URI itself


def test_the_a2a_card_lists_one_skill_per_tool(maf_agent):
    # Checks what MAF hands the card builder; the builder itself is shared by every adapter.
    pytest.importorskip("a2a")
    from agentkernel.framework.maf import maf as maf_module

    def lookup(city: str) -> str:
        """Look up a city."""
        return city

    maf_agent.attach_tool(lookup)
    with patch.object(maf_module.A2ACardBuilder, "build", return_value="card") as build:
        assert maf_agent.get_a2a_card() == "card"

    kwargs = build.call_args.kwargs
    assert (kwargs["name"], kwargs["description"]) == ("test-agent", "Test system message")
    assert [(skill.id, skill.description) for skill in kwargs["skills"]] == [("lookup", "Look up a city.")]


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

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)

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

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)

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

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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
            native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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
                native.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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
            return ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
    events = [event async for event in runner.stream(maf_agent, session, [AgentRequestText(prompt="Weather?")])]
    assert [type(event) for event in events] == [ToolCallStart, ToolCallArgs, ToolCallEnd, ToolCallResult]
    assert all(event.tool_call_id == "call1" for event in events)


@pytest.mark.asyncio
async def test_reasoning_only_stream_has_no_text_boundaries(runner, session, maf_agent, native_agent):
    async def mock_stream():
        yield AgentResponseUpdate(contents=[Content(type="text_reasoning", text="Thinking")])
        yield AgentResponseUpdate(contents=[Content(type="text_reasoning", text=" more")])

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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
async def test_a_failed_context_write_back_keeps_the_turn_but_not_the_context(runner, session, maf_agent, native_agent):
    # The model completed the turn, so the conversation is stored even when the context cannot be: losing the
    # turn would make the model forget an answer the user already saw.
    old_state = AgentSession(session_id=session.id).to_dict()
    session.set("maf", MAFSession())
    session.get("maf").set_state(old_state)
    session.set_framework_context({"safe": 1})

    native_response = AgentResponse(messages=[Message(role="assistant", contents=[Content.from_text("Hello")])])

    class Unserializable:
        pass

    def side_effect(*args, **kwargs):
        native_session = kwargs["session"]
        native_session.state["ak_context"] = {"bad": Unserializable()}
        native_session.state["turns"] = 1  # stands in for the history a provider appends during the run
        return native_response

    native_agent.run.side_effect = side_effect

    reply = await runner.run(maf_agent, session, [AgentRequestText(prompt="Hi")])
    assert isinstance(reply, AgentReplyText)
    assert "not picklable" in reply.response

    assert AgentSession.from_dict(session.get("maf").get_state()).state["turns"] == 1
    assert session.get_framework_context() == {"safe": 1}


@pytest.mark.asyncio
async def test_a_failed_context_write_back_in_a_stream_keeps_the_turn(runner, session, maf_agent, native_agent):
    session.set_framework_context({"safe": 1})

    class Unserializable:
        pass

    async def updates():
        yield AgentResponseUpdate(message_id="m1", contents=[Content.from_text("Hello")])

    def side_effect(*args, **kwargs):
        native_session = kwargs["session"]
        native_session.state["ak_context"] = {"bad": Unserializable()}
        native_session.state["turns"] = 1
        return ResponseStream(updates(), finalizer=AgentResponse.from_updates)

    native_agent.run.side_effect = side_effect

    events = [e async for e in runner.stream(maf_agent, session, [AgentRequestText(prompt="Hi")])]

    assert [e.content for e in events if isinstance(e, TextDelta)] == ["Hello"]
    assert AgentSession.from_dict(runner._session(session).get_state()).state["turns"] == 1
    assert session.get_framework_context() == {"safe": 1}


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

    native_agent.run.return_value = ResponseStream(mock_stream(), finalizer=AgentResponse.from_updates)
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


# --- Human in the loop: tool approval pause / resume ---------------------------------------------------------------
#
# These drive a real MAF `Agent` through a fake chat client, so MAF's own approval mechanics run: the gated tool is held
# back, the pending request is serialized into the record, and a resume on a fresh agent object (another replica)
# restores it. Nothing below mocks `Agent.run`.


class _ApprovalChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, ChatTelemetryLayer, BaseChatClient):
    """Asks for the `refund` tool for each order in `orders`, then answers from the tool results."""

    def __init__(self, orders: list[str], **kwargs):
        super().__init__(**kwargs)
        self.orders = orders

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if messages[-1].role == "tool":
            results = [c.result for c in messages[-1].contents if c.type == "function_result"]
            contents = [Content.from_text("done: " + "; ".join(str(r) for r in results))]
        else:
            contents = [
                Content.from_function_call(call_id=f"call_{order}", name="refund", arguments=json.dumps({"order_id": order})) for order in self.orders
            ]
        if stream:

            async def updates():
                yield ChatResponseUpdate(role="assistant", contents=contents, message_id="m1")

            return ResponseStream(updates(), finalizer=ChatResponse.from_updates)

        async def response():
            return ChatResponse(messages=[Message("assistant", contents)])

        return response()


@pytest.fixture
def refunded():
    return []


@pytest.fixture
def gated(refunded):
    """Builds a fresh runner + MAFAgent wrapping a fresh native agent, as another replica would."""

    def refund(order_id: str) -> str:
        """Refund an order."""
        refunded.append(order_id)
        return f"refunded {order_id}"

    def build(orders=("A1",)):
        native = Agent(_ApprovalChatClient(list(orders)), name="refunds", instructions="x", tools=[maf_tool(refund, approval_mode="always_require")])
        runner = MAFRunner()
        return runner, MAFAgent("refunds", runner, native)

    return build


async def _pause(gated, session, orders=("A1",)) -> AgentPausedReplyAny:
    runner, agent = gated(orders)
    reply = await runner.run(agent, session, [AgentRequestText(prompt="refund please")])
    assert isinstance(reply, AgentPausedReplyAny), reply
    return reply


def _decisions(reply: AgentPausedReplyAny, status: str = "approved") -> list[ResumeDecision]:
    return [ResumeDecision(id=i.id, status=status) for i in reply.interruptions]


class TestHumanInTheLoop:
    def test_the_runner_declares_it_can_pause(self):
        assert MAFRunner().supports_pause is True

    @pytest.mark.asyncio
    async def test_a_gated_tool_returns_a_paused_reply_without_running_it(self, gated, refunded, session):
        reply = await _pause(gated, session)

        assert refunded == []
        (interruption,) = reply.interruptions
        assert interruption.kind == "tool_call"
        assert interruption.tool_name == "refund"
        assert json.loads(interruption.arguments) == {"order_id": "A1"}
        assert reply.agent == "refunds" and reply.session_id == session.id

        (record,) = PausedRunState.list(session)
        assert record.id == reply.run_id and record.runner == "maf"
        assert set(record.payload) == {"session", "requests"}
        pickle.dumps(record.payload)  # the session store pickles it

    @pytest.mark.asyncio
    async def test_approving_on_a_fresh_agent_runs_the_tool_and_clears_the_record(self, gated, refunded, session):
        reply = await _pause(gated, session)
        session = pickle.loads(pickle.dumps(session))  # as loaded back from the session store on another replica

        runner, agent = gated()  # a different agent object: nothing survives in memory
        record = PausedRunState.get(session, reply.run_id)
        result = await runner.resume(agent, session, [], _decisions(reply), record)

        assert refunded == ["A1"]
        assert isinstance(result, AgentReplyText) and result.response == "done: refunded A1"
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["denied", "cancelled"])
    async def test_denying_or_cancelling_rejects_the_call(self, gated, refunded, session, status):
        reply = await _pause(gated, session)
        runner, agent = gated()

        result = await runner.resume(agent, session, [], _decisions(reply, status), PausedRunState.get(session, reply.run_id))

        assert refunded == []
        assert "rejected" in result.response
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_several_approvals_are_answered_together(self, gated, refunded, session):
        reply = await _pause(gated, session, orders=("A1", "B2"))
        first, second = reply.interruptions
        runner, agent = gated(("A1", "B2"))

        decisions = [ResumeDecision(id=first.id, status="approved"), ResumeDecision(id=second.id, status="denied")]
        result = await runner.resume(agent, session, [], decisions, PausedRunState.get(session, reply.run_id))

        assert refunded == ["A1"]
        assert "refunded A1" in result.response and "rejected" in result.response

    @pytest.mark.asyncio
    async def test_a_partial_resume_is_refused_and_keeps_the_record(self, gated, refunded, session):
        reply = await _pause(gated, session, orders=("A1", "B2"))
        runner, agent = gated(("A1", "B2"))
        partial = [ResumeDecision(id=reply.interruptions[0].id, status="approved")]

        with pytest.raises(ValueError, match="every pending approval"):
            await runner.resume(agent, session, [], partial, PausedRunState.get(session, reply.run_id))
        assert refunded == []
        assert [r.id for r in PausedRunState.list(session)] == [reply.run_id]

    @pytest.mark.asyncio
    async def test_a_payload_is_refused(self, gated, session):
        reply = await _pause(gated, session)
        runner, agent = gated()
        decisions = [ResumeDecision(id=reply.interruptions[0].id, status="approved", payload={"order_id": "Z9"})]

        with pytest.raises(ValueError, match="cannot deliver a structured answer"):
            await runner.resume(agent, session, [], decisions, PausedRunState.get(session, reply.run_id))

    @pytest.mark.asyncio
    async def test_a_prompt_alongside_a_decision_is_refused(self, gated, session):
        reply = await _pause(gated, session)
        runner, agent = gated()

        with pytest.raises(ValueError, match="cannot carry a prompt alongside a decision"):
            await runner.resume(agent, session, [AgentRequestText(prompt="and thanks")], _decisions(reply), PausedRunState.get(session, reply.run_id))

    @pytest.mark.asyncio
    async def test_a_new_prompt_while_a_pause_is_outstanding_is_refused(self, gated, session):
        reply = await _pause(gated, session)
        runner, agent = gated()

        with pytest.raises(ValueError, match=reply.run_id):
            await runner.run(agent, session, [AgentRequestText(prompt="something else")])
        with pytest.raises(ValueError, match=reply.run_id):
            _ = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="something else")])]
        assert [r.id for r in PausedRunState.list(session)] == [reply.run_id]

    @pytest.mark.asyncio
    async def test_another_framework_s_pause_does_not_block_this_one(self, gated, session):
        PausedRunState.add(session, agent="other", runner="openai", interruptions=[PausedInterruption(id="x1", kind="tool_call")])

        await _pause(gated, session)  # neither refused by, nor replacing, the other runner's record
        assert sorted(r.runner for r in PausedRunState.list(session)) == ["maf", "openai"]

    @pytest.mark.asyncio
    async def test_a_failed_resume_keeps_the_record_so_the_decision_can_be_retried(self, gated, refunded, session):
        reply = await _pause(gated, session)
        runner, agent = gated()
        agent.agent.run = AsyncMock(side_effect=RuntimeError("model unavailable"))

        result = await runner.resume(agent, session, [], _decisions(reply), PausedRunState.get(session, reply.run_id))
        assert isinstance(result, AgentReplyText) and refunded == []
        assert [r.id for r in PausedRunState.list(session)] == [reply.run_id]

        runner, agent = gated()  # the retry succeeds from the same record
        await runner.resume(agent, session, [], _decisions(reply), PausedRunState.get(session, reply.run_id))
        assert refunded == ["A1"] and PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_a_streamed_pause_ends_with_run_paused(self, gated, refunded, session):
        runner, agent = gated()

        events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund please")])]

        assert isinstance(events[-1], RunPaused)
        assert events[-1].agent == "refunds"
        assert [i.tool_name for i in events[-1].interruptions] == ["refund"]
        assert refunded == []
        assert [r.id for r in PausedRunState.list(session)] == [events[-1].run_id]

    @pytest.mark.asyncio
    async def test_resume_stream_runs_the_tool_and_clears_the_record(self, gated, refunded, session):
        runner, agent = gated()
        paused = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund please")])][-1]
        decisions = [ResumeDecision(id=i.id, status="approved") for i in paused.interruptions]

        runner, agent = gated()
        events = [e async for e in runner.resume_stream(agent, session, [], decisions, PausedRunState.get(session, paused.run_id))]

        assert refunded == ["A1"]
        assert "".join(e.content for e in events if isinstance(e, TextDelta)) == "done: refunded A1"
        assert not any(isinstance(e, RunPaused) for e in events)
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_a_failed_context_write_back_on_resume_stream_still_records_the_tool_result(self, gated, refunded, session):
        runner, agent = gated()
        paused = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund please")])][-1]
        decisions = [ResumeDecision(id=i.id, status="approved") for i in paused.interruptions]

        runner, agent = gated()
        runner._store_framework_context = MagicMock(side_effect=TypeError("framework_context is not picklable"))
        _ = [e async for e in runner.resume_stream(agent, session, [], decisions, PausedRunState.get(session, paused.run_id))]

        assert refunded == ["A1"]
        # The stored conversation already holds the tool's result, so clearing the record is safe: the next turn
        # continues from it rather than from the pre-pause snapshot with the approval still dangling.
        restored = AgentSession.from_dict(runner._session(session).get_state())
        history = [c.type for m in restored.state["in_memory"]["messages"] for c in m.contents]
        assert "function_result" in history
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_a_failed_context_write_back_on_resume_cannot_run_the_tool_twice(self, gated, refunded, session):
        reply = await _pause(gated, session)

        runner, agent = gated()
        runner._store_framework_context = MagicMock(side_effect=TypeError("framework_context is not picklable"))
        result = await runner.resume(agent, session, [], _decisions(reply), PausedRunState.get(session, reply.run_id))

        assert isinstance(result, AgentReplyText) and "not picklable" in result.response
        assert refunded == ["A1"]
        # The conversation holds the tool's result, so the record is gone: answering again cannot re-run the refund
        # from the pre-resume snapshot.
        assert PausedRunState.list(session) == []
        restored = AgentSession.from_dict(runner._session(session).get_state())
        assert "function_result" in [c.type for m in restored.state["in_memory"]["messages"] for c in m.contents]

    @pytest.mark.asyncio
    async def test_a_resume_whose_conversation_cannot_be_stored_keeps_the_record(self, gated, refunded, session):
        reply = await _pause(gated, session)

        runner, agent = gated()
        with patch.object(MAFSession, "set_state", side_effect=RuntimeError("session store unavailable")):
            result = await runner.resume(agent, session, [], _decisions(reply), PausedRunState.get(session, reply.run_id))

        assert isinstance(result, AgentReplyText) and "unavailable" in result.response
        assert [r.id for r in PausedRunState.list(session)] == [reply.run_id]  # nothing recorded the outcome: retryable

    @pytest.mark.asyncio
    async def test_resume_stream_refuses_a_partial_resume_before_streaming(self, gated, session):
        reply = await _pause(gated, session, orders=("A1", "B2"))
        runner, agent = gated(("A1", "B2"))
        partial = [ResumeDecision(id=reply.interruptions[0].id, status="approved")]

        with pytest.raises(ValueError, match="every pending approval"):
            _ = [e async for e in runner.resume_stream(agent, session, [], partial, PausedRunState.get(session, reply.run_id))]


class TestHumanInTheLoopThroughRuntime:
    """The same pause and resume, dispatched by Runtime as the REST, AG-UI and queue surfaces do."""

    @pytest.mark.asyncio
    async def test_runtime_routes_the_decision_to_resume(self, gated, refunded):
        runtime = Runtime(InMemorySessionStore())
        _, agent = gated()
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        paused = await runtime.run(agent, session, [AgentRequestText(prompt="refund please")])
        assert isinstance(paused, AgentPausedReplyAny) and refunded == []

        decision = AgentResumeRequestAny(run_id=paused.run_id, decisions=_decisions(paused))
        reply = await runtime.run(agent, session, [decision])

        assert refunded == ["A1"]
        assert reply.response == "done: refunded A1"
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_runtime_streams_the_pause_and_the_resume(self, gated, refunded):
        runtime = Runtime(InMemorySessionStore())
        _, agent = gated()
        runtime.register(agent)
        session = runtime.sessions().new("s2")

        chunks = [c async for c in runtime.stream(agent, session, [AgentRequestText(prompt="refund please")])]
        paused = next(c.event for c in chunks if isinstance(c.event, RunPaused))

        decision = AgentResumeRequestAny(run_id=paused.run_id, decisions=[ResumeDecision(id=i.id, status="approved") for i in paused.interruptions])
        chunks = [c async for c in runtime.stream(agent, session, [decision])]

        assert refunded == ["A1"]
        assert "".join(c.delta or "" for c in chunks) == "done: refunded A1"
        assert PausedRunState.list(session) == []


@pytest.mark.asyncio
async def test_a_client_disconnect_closes_the_native_stream(runner, session, maf_agent, native_agent):
    # A consumer that stops early (a client disconnect) must release the provider stream at once, not at garbage
    # collection; and an interrupted turn must not write the session back.
    closed = []

    async def updates():
        try:
            yield AgentResponseUpdate(message_id="m1", contents=[Content.from_text("Hello")])
            yield AgentResponseUpdate(message_id="m1", contents=[Content.from_text(" world")])
        finally:
            closed.append(True)

    native_agent.run.return_value = ResponseStream(updates(), finalizer=AgentResponse.from_updates)

    events = runner.stream(maf_agent, session, [AgentRequestText(prompt="Hi")])
    first = [await events.__anext__(), await events.__anext__()]  # MessageStart, the first TextDelta
    await events.aclose()

    assert isinstance(first[1], TextDelta)
    assert closed == [True]
    assert runner._session(session).get_state() is None
