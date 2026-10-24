"""One labelled reply, asserted to arrive the same way on every surface that carries it.

Nothing like this existed before: each surface had its own tests, and nothing compared them. That is
how four encoders came to disagree about the same value in the first place, so the comparison is the
point rather than any single assertion.

The fixture deliberately carries a `datetime` and a `Decimal`. Parity on a payload that was never at
risk proves nothing — those two are exactly the values the encoders rendered three different ways,
and one of them crashed on.

MCP and A2A run over the body a runner stores (`ResponseBuilder.build_response`), because since #780
that body is what the queue carries to their executors. A2A carries the payload as a data part
(#762), and its one allowed difference is the A2UI binding's: a single object goes out as a
one-item list of messages.
"""

import datetime
import decimal
import json
from unittest.mock import AsyncMock

import pytest

from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.event import DataMessage
from agentkernel.core.model import AgentReplyAny, StreamChunk

MEDIA_TYPE = "application/a2ui+json"


class _QueueClient:
    """Answers every MCP or A2A request with the body a runner stores for ``reply``."""

    def __init__(self, reply):
        from agentkernel.pipeline.request_client import QueuedReply

        _status, body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=reply)
        self._reply = QueuedReply(request_id="r1", body=body)

    async def request(self, body, protocol):
        return self._reply


async def _a2a_part(reply, monkeypatch):
    """The one part the A2A executor sends for ``reply``, through a real 1.x RequestContext."""
    from a2a.server.agent_execution import RequestContext
    from a2a.server.context import ServerCallContext
    from a2a.server.events import EventQueue
    from a2a.types import Message, Part, Role, SendMessageRequest

    from agentkernel.api.a2a.a2a import A2A

    class _Queue(EventQueue):
        def __init__(self):
            self.events = []

        async def enqueue_event(self, event) -> None:
            self.events.append(event)

    monkeypatch.setattr(A2A, "_client", _QueueClient(reply))
    message = Message(message_id="m1", role=Role.ROLE_USER, parts=[Part(text="hi")])
    context = RequestContext(ServerCallContext(), request=SendMessageRequest(message=message), task_id="t1", context_id="s1")
    queue = _Queue()
    await A2A.Executor("expenses").execute(context, queue)
    [event] = queue.events
    [part] = event.parts
    return part


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
async def test_mcp_carries_the_same_pair(labelled_reply, monkeypatch):
    from agentkernel.api.mcp.akmcp import MCP

    monkeypatch.setattr(MCP, "_client", _QueueClient(labelled_reply))
    result = await MCP.Executor("expenses").execute("s1", "hi", AsyncMock())

    assert result.structured_content == EXPECTED_CONTENT
    assert result.meta == {"media_type": MEDIA_TYPE}


@pytest.mark.asyncio
async def test_a2a_carries_the_same_pair(labelled_reply, monkeypatch):
    """A data part labelled in both places A2A and A2UI clients look; the object as a one-item list."""
    from a2a.helpers import get_data_parts

    part = await _a2a_part(labelled_reply, monkeypatch)

    assert get_data_parts([part]) == [[EXPECTED_CONTENT]]
    assert part.media_type == MEDIA_TYPE
    assert dict(part.metadata) == {"mimeType": MEDIA_TYPE}


@pytest.mark.asyncio
async def test_an_array_payload_is_reshaped_only_by_mcp(monkeypatch):
    """The one place parity cannot hold, and the only place it is allowed not to.

    A2UI on v0.9.1 is a sequence, so a reply may carry an array. Every surface here carries it
    unchanged except MCP, whose `structuredContent` is an object by specification. A2A included:
    an array is already the list of messages its binding requires.
    """
    from a2a.helpers import get_data_parts

    from agentkernel.api.mcp.akmcp import MCP
    from agentkernel.integration.agui.mapping import AGUIMapper

    content = [{"createSurface": {"surfaceId": "s1"}}, {"updateComponents": {}}]
    reply = AgentReplyAny(content=content, media_type=MEDIA_TYPE)

    rest = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=reply)["result"]
    stream = json.loads(ResponseBuilder.stream_chunk(StreamChunk(event=DataMessage(message_id="m1", content=content)), "s1"))
    agui = AGUIMapper.to_agui(DataMessage(message_id="m1", content=content, media_type=MEDIA_TYPE))

    assert rest == stream["event"]["content"] == agui.value == content
    assert get_data_parts([await _a2a_part(reply, monkeypatch)]) == [content]

    monkeypatch.setattr(MCP, "_client", _QueueClient(reply))
    mcp = await MCP.Executor("expenses").execute("s1", "hi", AsyncMock())

    assert mcp.structured_content == {"result": content}
    assert mcp.meta == {"media_type": MEDIA_TYPE, "fastmcp": {"wrap_result": True}}


def test_thread_history_records_the_same_bytes_from_either_path(labelled_reply):
    """The queue runner holds the response body's `result`; the direct handler holds the reply."""
    from agentkernel.integration.thread.recorder import ThreadRecorder

    direct = ThreadRecorder._as_thread_content(labelled_reply)
    queued = ThreadRecorder._as_thread_content(labelled_reply.content)

    assert direct == queued
    assert json.loads(direct) == EXPECTED_CONTENT


@pytest.mark.asyncio
async def test_every_surface_agrees_on_the_payload(labelled_reply, monkeypatch):
    """The assertion the file exists for: one value, every carrier, no divergence."""
    from a2a.helpers import get_data_parts

    from agentkernel.integration.agui.mapping import AGUIMapper

    rest = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=labelled_reply)["result"]
    _status, async_body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=labelled_reply)
    stream = json.loads(ResponseBuilder.stream_chunk(StreamChunk(event=DataMessage(message_id="m1", content=RAW_CONTENT)), "s1"))
    agui = AGUIMapper.to_agui(DataMessage(message_id="m1", content=RAW_CONTENT, media_type=MEDIA_TYPE))
    [[a2a]] = get_data_parts([await _a2a_part(labelled_reply, monkeypatch)])  # the binding's one-item list

    assert rest == async_body["result"] == stream["event"]["content"] == agui.value == a2a == EXPECTED_CONTENT


def test_an_unlabelled_reply_still_leaves_as_a_string_everywhere():
    """The other half of the guarantee: without a media type nothing above applies."""
    unlabelled = AgentReplyAny(content=RAW_CONTENT)

    rest = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=unlabelled)
    _status, async_body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=unlabelled)

    assert rest["result"] == json.dumps(EXPECTED_CONTENT)
    assert async_body["result"] == json.dumps(EXPECTED_CONTENT)
    assert "media_type" not in rest
    assert "media_type" not in async_body
