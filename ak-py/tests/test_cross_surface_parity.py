"""One labelled reply, asserted to arrive the same way on every surface that carries it.

Nothing like this existed before: each surface had its own tests, and nothing compared them. That is
how four encoders came to disagree about the same value in the first place, so the comparison is the
point rather than any single assertion.

The fixture deliberately carries a `datetime` and a `Decimal`. Parity on a payload that was never at
risk proves nothing — those two are exactly the values the encoders rendered three different ways,
and one of them crashed on.

A2A is absent because it does not import against the pinned SDK; it joins when the port issue adds
the data part.
"""

import datetime
import decimal
import json
from unittest.mock import AsyncMock, patch

import pytest

from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.event import DataMessage
from agentkernel.core.model import AgentReplyAny, StreamChunk

MEDIA_TYPE = "application/a2ui+json"

RAW_CONTENT = {
    "version": "v1.0",
    "createSurface": {
        "surfaceId": "expense_form",
        "submittedAt": datetime.datetime(2026, 9, 22, 14, 30),
        "amount": decimal.Decimal("250.00"),
    },
}

EXPECTED_CONTENT = {
    "version": "v1.0",
    "createSurface": {
        "surfaceId": "expense_form",
        "submittedAt": "2026-09-22T14:30:00",
        "amount": "250.00",
    },
}


@pytest.fixture
def labelled_reply() -> AgentReplyAny:
    return AgentReplyAny(content=RAW_CONTENT, media_type=MEDIA_TYPE)


def test_the_fixture_normalises_at_construction(labelled_reply):
    """Every surface below receives an already-safe payload; this is where that happens."""
    assert labelled_reply.content == EXPECTED_CONTENT


def test_rest_carries_the_object_and_the_label(labelled_reply):
    response = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=labelled_reply)

    assert response["result"] == EXPECTED_CONTENT
    assert response["media_type"] == MEDIA_TYPE


def test_websocket_and_async_carry_the_same_body(labelled_reply):
    """Both leave through the response dict the builder produced, as a JSON frame."""
    status, body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=labelled_reply)

    assert status == 200
    assert body["result"] == EXPECTED_CONTENT
    assert body["media_type"] == MEDIA_TYPE


def test_the_queue_gate_serialises_the_same_body(labelled_reply):
    """The body crosses a queue as bytes; before this work that call raised on a datetime."""
    from agentkernel.core.util.payload import PayloadCodec

    body = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=labelled_reply)

    assert json.loads(PayloadCodec.encode(body))["result"] == EXPECTED_CONTENT


def test_streaming_carries_the_same_pair(labelled_reply):
    chunk = StreamChunk(event=DataMessage(message_id="m1", content=RAW_CONTENT, media_type=MEDIA_TYPE))

    frame = json.loads(ResponseBuilder.stream_chunk(chunk, "s1"))

    assert frame["event"]["content"] == EXPECTED_CONTENT
    assert frame["event"]["media_type"] == MEDIA_TYPE


def test_agui_carries_the_same_pair(labelled_reply):
    from agentkernel.integration.agui.mapping import AGUIMapper

    event = AGUIMapper.to_agui(DataMessage(message_id="m1", content=RAW_CONTENT, media_type=MEDIA_TYPE))

    assert event.value == EXPECTED_CONTENT
    assert event.name == MEDIA_TYPE


@pytest.mark.asyncio
async def test_mcp_carries_the_same_pair(labelled_reply):
    from agentkernel.api.mcp.akmcp import MCP

    with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
        service_cls.return_value.run_multi = AsyncMock(return_value=labelled_reply)
        result = await MCP.Executor("expenses").execute("s1", "hi", AsyncMock())

    assert result.structured_content == EXPECTED_CONTENT
    assert result.meta == {"media_type": MEDIA_TYPE}


@pytest.mark.asyncio
async def test_an_array_payload_is_reshaped_only_by_mcp():
    """The one place parity cannot hold, and the only place it is allowed not to.

    A2UI on v0.9.1 is a sequence, so a reply may carry an array. Every surface here carries it
    unchanged except MCP, whose `structuredContent` is an object by specification.
    """
    from agentkernel.api.mcp.akmcp import MCP
    from agentkernel.integration.agui.mapping import AGUIMapper

    content = [{"createSurface": {"surfaceId": "s1"}}, {"updateComponents": {}}]
    reply = AgentReplyAny(content=content, media_type=MEDIA_TYPE)

    rest = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=reply)["result"]
    stream = json.loads(ResponseBuilder.stream_chunk(StreamChunk(event=DataMessage(message_id="m1", content=content)), "s1"))
    agui = AGUIMapper.to_agui(DataMessage(message_id="m1", content=content, media_type=MEDIA_TYPE))

    assert rest == stream["event"]["content"] == agui.value == content

    with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
        service_cls.return_value.run_multi = AsyncMock(return_value=reply)
        mcp = await MCP.Executor("expenses").execute("s1", "hi", AsyncMock())

    assert mcp.structured_content == {"result": content}
    assert mcp.meta == {"media_type": MEDIA_TYPE, "fastmcp": {"wrap_result": True}}


def test_thread_history_records_the_same_bytes_from_either_path(labelled_reply):
    """The queue runner holds the response body's `result`; the direct handler holds the reply."""
    from agentkernel.integration.thread.recorder import ThreadRecorder

    direct, _ = ThreadRecorder._as_thread_message(labelled_reply)
    queued, _ = ThreadRecorder._as_thread_message(labelled_reply.content)

    assert direct == queued
    assert json.loads(direct) == EXPECTED_CONTENT


def test_every_surface_agrees_on_the_payload(labelled_reply):
    """The assertion the file exists for: one value, every carrier, no divergence."""
    from agentkernel.integration.agui.mapping import AGUIMapper

    rest = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=labelled_reply)["result"]
    _status, async_body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=labelled_reply)
    stream = json.loads(ResponseBuilder.stream_chunk(StreamChunk(event=DataMessage(message_id="m1", content=RAW_CONTENT)), "s1"))
    agui = AGUIMapper.to_agui(DataMessage(message_id="m1", content=RAW_CONTENT, media_type=MEDIA_TYPE))

    assert rest == async_body["result"] == stream["event"]["content"] == agui.value == EXPECTED_CONTENT


def test_an_unlabelled_reply_still_leaves_as_a_string_everywhere():
    """The other half of the guarantee: without a media type nothing above applies."""
    unlabelled = AgentReplyAny(content=RAW_CONTENT)

    rest = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=unlabelled)
    _status, async_body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=unlabelled)

    assert rest["result"] == json.dumps(EXPECTED_CONTENT)
    assert async_body["result"] == json.dumps(EXPECTED_CONTENT)
    assert "media_type" not in rest
    assert "media_type" not in async_body


@pytest.fixture
def paused_reply():
    from agentkernel.core.event import PausedInterruption
    from agentkernel.core.model import AgentPausedReplyAny

    return AgentPausedReplyAny(
        run_id="run-1",
        session_id="s1",
        agent="assistant",
        interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="send_summary_email", arguments='{"recipient": "anne@example.com"}')],
    )


def test_every_thread_recording_site_stores_the_same_pause(paused_reply):
    """The four sites hold four different things; only one of them is the reply itself.

    Each is translated here exactly as its own surface translates it — the SSE handler and both
    queue runners rebuild `AgentPausedReplyAny` from what they hold, so the stored content always
    comes from that model's own validator rather than four hand-assembled dicts.
    """
    from agentkernel.core.event import RunPaused
    from agentkernel.core.model import AgentPausedReplyAny
    from agentkernel.integration.thread.recorder import ThreadRecorder
    from agentkernel.pipeline.agent_runner import AgentRunner

    event = RunPaused(run_id=paused_reply.run_id, agent=paused_reply.agent, interruptions=paused_reply.interruptions)
    _status, body = ResponseBuilder.build_response(202, "s1", rest_api_mode=False, result=paused_reply)
    streamed_event = json.loads(ResponseBuilder.stream_chunk(StreamChunk(event=event), "s1"))["event"]

    direct = ThreadRecorder._as_thread_message(paused_reply)
    sse = ThreadRecorder._as_thread_message(
        AgentPausedReplyAny(run_id=event.run_id, session_id="s1", agent=event.agent, interruptions=event.interruptions)
    )
    queued = ThreadRecorder._as_thread_message(AgentRunner._reply_to_record(body, "s1"))
    queued_stream = ThreadRecorder._as_thread_message(AgentRunner._paused_reply(streamed_event, "s1"))

    assert direct == sse == queued == queued_stream
    assert direct[0]["interruptions"][0]["tool_name"] == "send_summary_email"
    assert direct[1] == "application/json"


def test_the_pause_survives_the_stream_chunk_round_trip(paused_reply):
    """The queue-streaming runner reads a serialised event, where `exclude_none` has dropped keys."""
    from agentkernel.core.event import RunPaused
    from agentkernel.pipeline.agent_runner import AgentRunner

    event = RunPaused(run_id="run-1", agent="assistant", interruptions=paused_reply.interruptions)
    streamed_event = json.loads(ResponseBuilder.stream_chunk(StreamChunk(event=event), "s1"))["event"]

    assert "message" not in streamed_event["interruptions"][0]
    assert AgentRunner._paused_reply(streamed_event, "s1").content == paused_reply.content
