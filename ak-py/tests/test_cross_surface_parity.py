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


def test_thread_history_records_the_same_bytes_from_either_path(labelled_reply):
    """The queue runner holds the response body's `result`; the direct handler holds the reply."""
    from agentkernel.integration.thread.recorder import ThreadRecorder

    direct = ThreadRecorder._as_thread_content(labelled_reply)
    queued = ThreadRecorder._as_thread_content(labelled_reply.content)

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
