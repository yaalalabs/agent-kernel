"""Focused tests for the LiveKit edge gateway with the SDK boundary stubbed.

The real ``rtc``/``Room`` stack needs a live WebRTC connection, so these tests exercise the
gateway's own logic (audio batching into the input queue, chat parsing, outbound playback,
barge-in, and transcript publication) against simple fakes.
"""

import asyncio
import base64
import logging
import types

import pytest

import agentkernel.integration.livekit.adapter as livekit_adapter
from agentkernel.core.event import AudioDelta, Interrupt, TextDelta
from agentkernel.core.model import AgentRequestText, StreamChunk
from agentkernel.integration.livekit.adapter import LiveKitEdgeGateway


class _FakeRtc:
    @staticmethod
    def AudioFrame(**kwargs):
        return types.SimpleNamespace(**kwargs)


class _Producer:
    def __init__(self):
        self.calls = []

    def enqueue(self, **kwargs):
        self.calls.append(kwargs)


class _AudioSource:
    def __init__(self):
        self.frames = []
        self.clears = 0

    async def capture_frame(self, frame):
        self.frames.append(frame)

    def clear_queue(self):
        self.clears += 1


def _gateway() -> LiveKitEdgeGateway:
    """Build a gateway without the constructor's config/token work."""
    gateway = object.__new__(LiveKitEdgeGateway)
    gateway.session_id = "s1"
    gateway.agent_name = "general"
    gateway.producer = None
    gateway._pending = None
    gateway._sender_task = None
    gateway._loop = None
    gateway.room = None
    gateway.audio_source = None
    gateway._transcript = []
    gateway._interrupted = False
    return gateway


def _packet(text: str, topic: str = "lk-chat"):
    return types.SimpleNamespace(topic=topic, data=text.encode("utf-8"), participant=types.SimpleNamespace(identity="human"))


class TestInboundStaging:
    @pytest.mark.asyncio
    async def test_enqueue_stages_and_the_sender_delivers_to_the_producer(self):
        gateway = _gateway()
        gateway.producer = _Producer()
        gateway._pending = asyncio.Queue(maxsize=4)
        sender = asyncio.create_task(gateway._drain_requests())
        try:
            gateway._enqueue(AgentRequestText(prompt="hi", name="general"))
            for _ in range(50):
                if gateway.producer.calls:
                    break
                await asyncio.sleep(0.01)
        finally:
            sender.cancel()

        [call] = gateway.producer.calls
        assert call["group_id"] == "s1"
        assert call["attributes"]["integration"] == "livekit"
        assert call["body"].session_id == "s1"

    @pytest.mark.asyncio
    async def test_enqueue_drops_a_frame_when_the_staging_queue_is_full(self, caplog):
        gateway = _gateway()
        gateway.producer = _Producer()
        gateway._pending = asyncio.Queue(maxsize=1)
        gateway._pending.put_nowait(("body", "id", {}))

        with caplog.at_level(logging.WARNING):
            gateway._enqueue(AgentRequestText(prompt="hi", name="general"))

        assert gateway._pending.qsize() == 1
        assert any("full" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_chat_message_parses_json_and_plain_text(self, monkeypatch):
        gateway = _gateway()
        seen = []
        monkeypatch.setattr(gateway, "_enqueue", lambda request: seen.append(request))

        gateway._handle_chat_message(_packet('{"message": "hello"}'))
        gateway._handle_chat_message(_packet("plain text", topic="chat"))
        gateway._handle_chat_message(_packet("ignored", topic="some-other-topic"))

        assert [request.prompt for request in seen] == ["hello", "plain text"]


class TestOutboundDelivery:
    @pytest.mark.asyncio
    async def test_audio_delta_is_played_immediately(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        gateway = _gateway()
        source = _AudioSource()
        gateway.audio_source = source
        gateway._loop = asyncio.get_running_loop()

        audio = base64.b64encode(b"\x00\x00" * 10).decode("utf-8")
        await gateway.deliver_chunk(StreamChunk(event=AudioDelta(message_id="m", content=audio)), {})

        assert len(source.frames) == 1
        assert source.frames[0].samples_per_channel == 10

    @pytest.mark.asyncio
    async def test_transcript_is_accumulated_and_published_on_done(self, monkeypatch):
        gateway = _gateway()
        published = []

        async def fake_publish(text):
            published.append(text)

        monkeypatch.setattr(gateway, "_publish_text", fake_publish)

        await gateway.deliver_chunk(StreamChunk(event=TextDelta(message_id="m", content="Hello ")), {})
        await gateway.deliver_chunk(StreamChunk(event=TextDelta(message_id="m", content="world")), {})
        await gateway.deliver_chunk(StreamChunk(done=True), {})

        assert published == ["Hello world"]
        assert gateway._transcript == []

    @pytest.mark.asyncio
    async def test_interrupt_clears_playback_and_drops_the_partial_transcript(self, monkeypatch):
        gateway = _gateway()
        source = _AudioSource()
        gateway.audio_source = source
        gateway._loop = asyncio.get_running_loop()

        published = []
        monkeypatch.setattr(gateway, "_publish_text", lambda text: published.append(text))

        await gateway.deliver_chunk(StreamChunk(event=TextDelta(message_id="m", content="half")), {})
        await gateway.deliver_chunk(StreamChunk(event=Interrupt()), {})
        await asyncio.sleep(0)  # let the loop run the marshalled clear_queue callback
        await gateway.deliver_chunk(StreamChunk(done=True), {})

        assert source.clears == 1
        assert published == []  # the interrupted sentence is never published
        assert gateway._interrupted is False
