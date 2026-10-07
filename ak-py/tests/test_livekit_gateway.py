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
from agentkernel.core.model import AgentRequestText, AgentRequestVoice, StreamChunk
from agentkernel.integration.livekit.adapter import LiveKitEdgeGateway


class _FakeRtc:
    @staticmethod
    def AudioFrame(**kwargs):
        return types.SimpleNamespace(**kwargs)


class _Producer:
    def __init__(self):
        self.calls = []

    def enqueue(self, adapter_name, request):
        self.calls.append({"adapter_name": adapter_name, "request": request})


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
    gateway.agent = "general"
    gateway._producer = None
    gateway._pending = None
    gateway._sender_task = None
    gateway._loop = None
    gateway.room = None
    gateway.audio_source = None
    gateway._transcript = []
    gateway._interrupted = False
    gateway._input_batch_ms = 100
    gateway._input_batch_bytes = 4800
    return gateway


def _packet(text: str, topic: str = "lk-chat"):
    return types.SimpleNamespace(topic=topic, data=text.encode("utf-8"), participant=types.SimpleNamespace(identity="human"))


class _FakeFrame:
    def __init__(self, data: bytes):
        self.data = types.SimpleNamespace(tobytes=lambda: data)


class _FakeAudioStream:
    def __init__(self, frames):
        self._frames = frames

    def __aiter__(self):
        self._it = iter(self._frames)
        return self

    async def __anext__(self):
        try:
            return types.SimpleNamespace(frame=next(self._it))
        except StopIteration:
            raise StopAsyncIteration


def _fake_rtc(frames):
    class _Rtc:
        @staticmethod
        def AudioStream(track, **kwargs):
            return _FakeAudioStream([_FakeFrame(f) for f in frames])

    return _Rtc


class TestToken:
    @staticmethod
    def _claims(token: str) -> dict:
        import json

        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))

    @pytest.mark.parametrize("agent_name, identity", [("support", "agent-support"), (None, "agent-general")])
    def test_generated_token_names_the_agent_participant(self, monkeypatch, agent_name, identity):
        cfg = types.SimpleNamespace(
            livekit=types.SimpleNamespace(url="wss://lk", agent="", api_key="key", api_secret="secret" * 8),
            execution=types.SimpleNamespace(realtime=types.SimpleNamespace(input_batch_ms=100)),
        )
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: cfg))

        gateway = LiveKitEdgeGateway(agent_name=agent_name, session_id="room-1")

        claims = self._claims(gateway.token)
        assert claims["sub"] == identity
        assert claims["video"]["room"] == "room-1"
        assert gateway.agent == agent_name


class TestInboundStaging:
    @pytest.mark.asyncio
    async def test_enqueue_stages_and_the_sender_delivers_to_the_producer(self):
        gateway = _gateway()
        gateway._producer = _Producer()
        gateway._pending = asyncio.Queue(maxsize=4)
        sender = asyncio.create_task(gateway._drain_requests())
        try:
            gateway._stage_request(AgentRequestText(prompt="hi"))
            for _ in range(50):
                if gateway._producer.calls:
                    break
                await asyncio.sleep(0.01)
        finally:
            sender.cancel()

        [call] = gateway._producer.calls
        assert call["adapter_name"] == "livekit"
        assert call["request"].session_id == "s1"
        assert call["request"].agent == "general"
        assert call["request"].reply_context == {"session_id": "s1"}

    def test_enqueue_carries_no_agent_when_none_is_configured(self):
        gateway = _gateway()
        gateway.agent = None

        assert gateway._enqueue(AgentRequestText(prompt="hi")).agent is None

    def test_integration_producer_stamps_the_configured_agent_on_the_queued_body(self):
        from agentkernel.integration.adapter.producer import IntegrationProducer

        sent = []
        producer = object.__new__(IntegrationProducer)
        producer._producer = types.SimpleNamespace(enqueue=lambda body, **kwargs: sent.append((body, kwargs)))
        gateway = _gateway()

        producer.enqueue(gateway.name, gateway._enqueue(AgentRequestText(prompt="hi")))

        [(body, kwargs)] = sent
        assert body.agent == "general"
        assert body.session_id == "s1"
        assert kwargs["group_id"] == "s1"
        assert kwargs["attributes"]["integration"] == "livekit"
        assert kwargs["attributes"]["reply_session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_enqueue_drops_a_frame_when_the_staging_queue_is_full(self, caplog):
        gateway = _gateway()
        gateway._producer = _Producer()
        gateway._pending = asyncio.Queue(maxsize=1)
        gateway._pending.put_nowait("staged")

        with caplog.at_level(logging.WARNING):
            gateway._stage_request(AgentRequestText(prompt="hi"))

        assert gateway._pending.qsize() == 1
        assert any("full" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_chat_message_parses_json_and_plain_text(self, monkeypatch):
        gateway = _gateway()
        seen = []
        monkeypatch.setattr(gateway, "_stage_request", lambda request: seen.append(request))

        gateway._handle_chat_message(_packet('{"message": "hello"}'))
        gateway._handle_chat_message(_packet("plain text", topic="chat"))
        gateway._handle_chat_message(_packet("ignored", topic="some-other-topic"))

        assert [request.prompt for request in seen] == ["hello", "plain text"]


class TestInboundAudioBatching:
    @pytest.mark.asyncio
    async def test_pass_through_enqueues_every_frame_when_batch_is_zero(self, monkeypatch):
        frames = [b"\x01\x02", b"\x03\x04", b"\x05\x06"]
        monkeypatch.setattr(livekit_adapter, "rtc", _fake_rtc(frames))
        gateway = _gateway()
        gateway._input_batch_bytes = 0
        seen = []
        gateway._stage_request = lambda request: seen.append(request)

        await gateway._process_incoming_audio(object())

        assert [base64.b64decode(request.audio_data) for request in seen] == frames

    @pytest.mark.asyncio
    async def test_batches_frames_to_the_configured_size_and_flushes_the_tail(self, monkeypatch):
        frames = [b"\x00" * 3, b"\x00" * 3, b"\x00" * 3, b"\x00" * 2]
        monkeypatch.setattr(livekit_adapter, "rtc", _fake_rtc(frames))
        gateway = _gateway()
        gateway._input_batch_bytes = 6
        seen = []
        gateway._stage_request = lambda request: seen.append(request)

        await gateway._process_incoming_audio(object())

        assert [len(base64.b64decode(request.audio_data)) for request in seen] == [6, 5]

    def test_enqueue_audio_base64_encodes_a_voice_request(self):
        gateway = _gateway()
        seen = []
        gateway._stage_request = lambda request: seen.append(request)

        gateway._stage_request(gateway._enqueue_audio(b"\x01\x02\x03\x04"))

        [request] = seen
        assert isinstance(request, AgentRequestVoice)
        assert request.audio_data == base64.b64encode(b"\x01\x02\x03\x04").decode("utf-8")


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

    @pytest.mark.asyncio
    async def test_the_turn_after_an_interrupted_one_is_published(self, monkeypatch):
        """The interrupted turn's done resets the state, so the next turn is published normally."""
        gateway = _gateway()
        gateway.audio_source = _AudioSource()
        gateway._loop = asyncio.get_running_loop()

        published = []

        async def fake_publish(text):
            published.append(text)

        monkeypatch.setattr(gateway, "_publish_text", fake_publish)

        await gateway.deliver_chunk(StreamChunk(event=TextDelta(message_id="m1", content="cut off")), {})
        await gateway.deliver_chunk(StreamChunk(event=Interrupt()), {})
        await gateway.deliver_chunk(StreamChunk(done=True), {})
        await gateway.deliver_chunk(StreamChunk(event=TextDelta(message_id="m2", content="next answer")), {})
        await gateway.deliver_chunk(StreamChunk(done=True), {})

        assert published == ["next answer"]
