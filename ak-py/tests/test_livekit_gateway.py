"""Focused tests for the LiveKit edge gateway with the SDK boundary stubbed.

The real ``rtc``/``Room`` stack needs a live WebRTC connection, so these tests exercise the
gateway's own logic (audio batching into the input queue, chat parsing, outbound playback,
barge-in, and transcript publication) against simple fakes.
"""

import asyncio
import base64
import json
import logging
import threading
import types
import warnings

import pytest

import agentkernel.integration.livekit.adapter as livekit_adapter
from agentkernel.core.event import AgentChanged, AudioDelta, InputTranscript, Interrupt, TextDelta
from agentkernel.core.model import AgentRequestText, AgentRequestVoice, StreamChunk
from agentkernel.integration.adapter.base import TranscriptLine
from agentkernel.integration.livekit.adapter import LiveKitEdgeGateway


class _FakeRtc:
    @staticmethod
    def AudioFrame(**kwargs):
        return types.SimpleNamespace(**kwargs)


class _Producer:
    def __init__(self):
        self.calls = []

    def enqueue(self, adapter_name, request, attributes=None):
        self.calls.append({"adapter_name": adapter_name, "request": request, "attributes": attributes})


class _AudioSource:
    def __init__(self):
        self.frames = []
        self.clears = 0
        self.playouts = 0

    async def capture_frame(self, frame):
        self.frames.append(frame)

    def clear_queue(self):
        self.clears += 1

    async def wait_for_playout(self):
        self.playouts += 1


class _Track:
    """A published LiveKit audio track: records whether it is muted."""

    def __init__(self, name="ai-voice"):
        self.name = name
        self.muted = False

    def mute(self):
        self.muted = True

    def unmute(self):
        self.muted = False


class _TextWriter:
    """A LiveKit text stream writer: records what was written and whether it was closed."""

    def __init__(self, topic, attributes, sender_identity):
        self.topic = topic
        self.attributes = attributes
        self.sender_identity = sender_identity
        self.written = []
        self.closed = False

    async def write(self, text):
        self.written.append(text)

    async def aclose(self):
        self.closed = True


class _LocalParticipant:
    def __init__(self, identity=None):
        self.identity = identity
        self.attributes = {}
        self.chat = []
        self.tracks = []
        self.streams = []
        self.texts = []

    async def publish_track(self, track, options):
        self.tracks.append(track)

    async def set_attributes(self, attributes):
        self.attributes.update(attributes)

    async def publish_data(self, payload, reliable=True, topic=""):
        self.chat.append(json.loads(payload)["message"])

    async def stream_text(self, *, topic="", attributes=None, sender_identity=None, **kwargs):
        writer = _TextWriter(topic, dict(attributes or {}), sender_identity)
        self.streams.append(writer)
        return writer

    async def send_text(self, text, *, topic="", attributes=None, **kwargs):
        self.texts.append({"text": text, "topic": topic, "attributes": dict(attributes or {})})


class _Room:
    """A LiveKit room connection: records its handlers, its connect options and its disconnects."""

    def __init__(self, identity=None):
        self.local_participant = _LocalParticipant(identity)
        self.handlers = {}
        self.options = None
        self.disconnects = 0

    def on(self, event, callback):
        self.handlers[event] = callback
        return callback

    async def connect(self, url, token, options):
        self.options = options
        self.local_participant.identity = TestToken._claims(token)["sub"]

    async def disconnect(self):
        self.disconnects += 1


def _participant(agent=None, identity="agent-general", muted=False):
    participant = LiveKitEdgeGateway._AgentParticipant(agent, identity, "token")
    participant.room = _Room(identity)
    participant.audio_source = _AudioSource()
    participant.track = _Track()
    participant.track.sid = f"TR_{identity}"
    participant.track.muted = muted
    return participant


def _gateway(*agents) -> LiveKitEdgeGateway:
    """Build a gateway without the constructor's config/token work: one participant per agent named,
    or a single participant speaking for every agent."""
    gateway = object.__new__(LiveKitEdgeGateway)
    gateway.session_id = "s1"
    gateway.room_url = "wss://lk"
    gateway.agent = "general"
    gateway._api_key, gateway._api_secret = "key", "secret" * 8
    gateway._producer = None
    gateway._pending = None
    gateway._sender_task = None
    gateway._loop = None
    # As in a room: the first participant is heard, every other one is muted.
    gateway._participants = [_participant(agent, f"agent-{agent}", muted=index > 0) for index, agent in enumerate(agents)] or [_participant()]
    gateway._by_agent = {participant.agent: participant for participant in gateway._participants if participant.agent}
    gateway._own_identities = {participant.identity for participant in gateway._participants}
    gateway._active = gateway._participants[0]
    gateway._joining = set()
    gateway._warned_agents = set()
    gateway._speaking_agent = None
    gateway._background_tasks = set()
    gateway._transcript = []
    gateway._interrupted = False
    gateway._line_parts = []
    gateway._line_message_id = None
    gateway._caption = None
    gateway._caption_queue = None
    gateway._caption_task = None
    gateway._caller_identity = None
    gateway._caller_track_sid = None
    gateway._ending = False
    gateway._end_sent = False
    gateway._connected = False
    gateway._hooks = None
    gateway._ready = threading.Event()
    gateway.name = "livekit"
    gateway._input_batch_ms = 100
    gateway._input_batch_bytes = 4800
    return gateway


def _config(monkeypatch):
    cfg = types.SimpleNamespace(
        livekit=types.SimpleNamespace(url="wss://lk", agent="", api_key="key", api_secret="secret" * 8),
        execution=types.SimpleNamespace(realtime=types.SimpleNamespace(input_batch_ms=100)),
    )
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: cfg))


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
        _config(monkeypatch)

        gateway = LiveKitEdgeGateway(agent_name=agent_name, session_id="room-1")

        claims = self._claims(gateway.token)
        assert claims["sub"] == identity
        assert claims["video"]["room"] == "room-1"
        assert gateway.agent == agent_name

    def test_an_announced_agent_gets_a_token_of_its_own(self, monkeypatch):
        _config(monkeypatch)
        gateway = LiveKitEdgeGateway(agent_name="supervisor", session_id="room-1")

        claims = self._claims(gateway._mint_token("billing"))

        assert claims["sub"] == "agent-billing"
        assert claims["name"] == "billing Agent"
        assert claims["video"]["room"] == "room-1"
        # Lets the participant set its ak.active attribute.
        assert claims["video"]["canUpdateOwnMetadata"] is True


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

    def test_send_text_with_no_loop_yet_is_dropped(self):
        gateway = _gateway()

        assert gateway.send_text("nudge") is False

    def test_send_text_after_the_gateways_loop_closed_is_dropped(self):
        gateway = _gateway()
        loop = asyncio.new_event_loop()
        loop.close()
        gateway._loop = loop

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            assert gateway.send_text("nudge") is False

        assert not [warning for warning in seen if "never awaited" in str(warning.message)]

    @pytest.mark.asyncio
    async def test_send_text_from_the_gateways_own_loop_stages_at_once(self):
        gateway = _gateway()
        gateway._producer = _Producer()
        gateway._pending = asyncio.Queue(maxsize=4)
        gateway._loop = asyncio.get_running_loop()

        assert gateway.send_text("the call went quiet") is True
        [staged] = [gateway._pending.get_nowait()]
        assert staged.requests[0].prompt == "the call went quiet"

    @pytest.mark.asyncio
    async def test_send_text_from_another_thread_stages_on_the_gateways_loop(self):
        gateway = _gateway()
        gateway._producer = _Producer()
        gateway._pending = asyncio.Queue(maxsize=4)
        gateway._loop = asyncio.get_running_loop()

        result = await asyncio.to_thread(gateway.send_text, "nudge from another thread")

        assert result is True
        staged = gateway._pending.get_nowait()
        assert staged.requests[0].prompt == "nudge from another thread"

    @pytest.mark.asyncio
    async def test_send_text_once_the_gateway_is_ending_is_dropped(self):
        gateway = _gateway()
        gateway._producer = _Producer()
        gateway._pending = asyncio.Queue(maxsize=4)
        gateway._loop = asyncio.get_running_loop()
        gateway._ending = True

        assert gateway.send_text("too late") is False

    def test_send_text_that_times_out_is_dropped_and_its_future_is_cancelled(self, monkeypatch):
        """The gateway's own loop could not confirm staging in time: reported as False, and the scheduled
        staging is cancelled on a best-effort basis so it cannot run late."""
        gateway = _gateway()
        gateway._loop = asyncio.new_event_loop()  # never run: send_text must not need it to actually execute

        class _TimedOutFuture:
            cancelled = False

            def result(self, timeout=None):
                raise TimeoutError("the gateway's loop did not answer in time")

            def cancel(self):
                self.cancelled = True

        future = _TimedOutFuture()

        def fake_dispatch(coro, loop):
            coro.close()  # never run, so it must not warn about an un-awaited coroutine
            return future

        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", fake_dispatch)

        assert gateway.send_text("nudge") is False
        assert future.cancelled is True
        gateway._loop.close()

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
        source = gateway._active.audio_source
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
        source = gateway._active.audio_source
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


def _room_rtc(fail_on=None, hang_on=None):
    """Stands in for ``livekit.rtc`` while a gateway joins the room; ``rooms`` lists every room it opened.
    The ``fail_on``-th room refuses to connect; the ``hang_on``-th never finishes connecting."""
    rooms = []

    def room():
        opened = _Room()
        rooms.append(opened)
        if fail_on == len(rooms):

            async def refuse(url, token, options):
                raise ConnectionError("join refused")

            opened.connect = refuse
        if hang_on == len(rooms):

            async def hang(url, token, options):
                await asyncio.Event().wait()

            opened.connect = hang
        return opened

    return types.SimpleNamespace(
        Room=room,
        RoomOptions=lambda **kwargs: types.SimpleNamespace(**kwargs),
        AudioSource=lambda **kwargs: _AudioSource(),
        LocalAudioTrack=types.SimpleNamespace(create_audio_track=lambda name, source: _Track(name)),
        TrackPublishOptions=lambda **kwargs: types.SimpleNamespace(**kwargs),
        TrackSource=types.SimpleNamespace(SOURCE_MICROPHONE="microphone"),
        TrackKind=types.SimpleNamespace(KIND_AUDIO="audio"),
        AudioFrame=lambda **kwargs: types.SimpleNamespace(**kwargs),
        rooms=rooms,
    )


class TestMultiAgentRoom:
    """The gateway starts as the one participant that hears the human; the team the conversation
    announces joins as participants of their own, each with its own track, with nothing configured."""

    TEAM = ["supervisor", "billing", "tech_support"]

    @staticmethod
    def _gateway(monkeypatch, **rtc_options):
        _config(monkeypatch)
        rtc = _room_rtc(**rtc_options)
        monkeypatch.setattr(livekit_adapter, "rtc", rtc)
        monkeypatch.setattr(LiveKitEdgeGateway, "_init_producer", lambda self: None)
        return LiveKitEdgeGateway(agent_name="supervisor", session_id="room-1"), rtc.rooms

    @staticmethod
    async def _started(gateway):
        task = asyncio.create_task(gateway.start())
        for _ in range(100):
            if gateway._connected or task.done():
                break
            await asyncio.sleep(0.01)
        return task

    @staticmethod
    async def _announce(gateway, agents):
        """Deliver the conversation's opening AgentChanged, then let the joins and attribute updates land."""
        await gateway.deliver_chunk(StreamChunk(event=AgentChanged(agent="supervisor", agents=agents)), {})
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not gateway._joining:
                break
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_the_gateway_starts_as_the_one_participant_that_hears_the_human(self, monkeypatch):
        gateway, rooms = self._gateway(monkeypatch)
        task = await self._started(gateway)
        try:
            [room] = rooms
            assert room.local_participant.identity == "agent-supervisor"
            assert room.options.auto_subscribe is True
            assert sorted(room.handlers) == ["data_received", "disconnected", "track_subscribed"]
            assert len(room.local_participant.tracks) == 1
        finally:
            await gateway.stop()
            await task

        assert room.disconnects == 1

    @pytest.mark.asyncio
    async def test_the_announced_team_joins_as_participants_of_their_own(self, monkeypatch):
        gateway, rooms = self._gateway(monkeypatch)
        task = await self._started(gateway)
        try:
            await self._announce(gateway, self.TEAM)

            assert [room.local_participant.identity for room in rooms] == ["agent-supervisor", "agent-billing", "agent-tech_support"]
            assert [room.options.auto_subscribe for room in rooms] == [True, False, False]
            assert [sorted(room.handlers) for room in rooms] == [
                ["data_received", "disconnected", "track_subscribed"],
                ["disconnected"],
                ["disconnected"],
            ]
            assert all(len(room.local_participant.tracks) == 1 for room in rooms)
            assert [room.local_participant.attributes for room in rooms] == [{"ak.active": "true"}, {"ak.active": "false"}, {"ak.active": "false"}]
            # Only the agent with the call shows as unmuted.
            assert [participant.track.muted for participant in gateway._participants] == [False, True, True]
            assert gateway._own_identities == {"agent-supervisor", "agent-billing", "agent-tech_support"}
        finally:
            await gateway.stop()
            await task

        assert [room.disconnects for room in rooms] == [1, 1, 1]

    @pytest.mark.asyncio
    async def test_a_reconnect_announcing_the_team_again_joins_no_one_twice(self, monkeypatch):
        gateway, rooms = self._gateway(monkeypatch)
        task = await self._started(gateway)
        try:
            await self._announce(gateway, self.TEAM)
            await self._announce(gateway, self.TEAM)

            assert len(rooms) == 3
        finally:
            await gateway.stop()
            await task

    @pytest.mark.asyncio
    async def test_a_team_announced_while_the_first_participant_joins_waits_for_it(self, monkeypatch):
        """The conversation can announce its team before the gateway is in the room; no one joins until it is."""
        gateway, rooms = self._gateway(monkeypatch)
        open_room, release = livekit_adapter.rtc.Room, asyncio.Event()

        def room():
            opened = open_room()
            if len(rooms) == 1:
                connect = opened.connect

                async def connect_when_released(url, token, options):
                    await release.wait()
                    await connect(url, token, options)

                opened.connect = connect_when_released
            return opened

        monkeypatch.setattr(livekit_adapter.rtc, "Room", room)
        task = await self._started(gateway)
        try:
            assert not gateway._connected
            await self._announce(gateway, self.TEAM)
            assert len(rooms) == 1 and not gateway._joining

            release.set()
            for _ in range(200):
                await asyncio.sleep(0.01)
                if len(rooms) == 3 and not gateway._joining:
                    break
            assert [room.local_participant.identity for room in rooms] == ["agent-supervisor", "agent-billing", "agent-tech_support"]
            assert sorted(gateway._by_agent) == sorted(self.TEAM)
        finally:
            release.set()
            await gateway.stop()
            await task

    @pytest.mark.asyncio
    async def test_a_single_agent_stays_one_participant(self, monkeypatch):
        gateway, rooms = self._gateway(monkeypatch)
        task = await self._started(gateway)
        try:
            await self._announce(gateway, ["supervisor"])

            assert len(rooms) == 1
            assert rooms[0].local_participant.attributes == {}
        finally:
            await gateway.stop()
            await task

    @pytest.mark.asyncio
    async def test_an_agent_that_cannot_join_speaks_through_the_first(self, monkeypatch, caplog):
        gateway, rooms = self._gateway(monkeypatch, fail_on=2)
        task = await self._started(gateway)
        try:
            with caplog.at_level(logging.WARNING):
                await self._announce(gateway, self.TEAM)
                await gateway.deliver_chunk(StreamChunk(event=AgentChanged(agent="billing", previous_agent="supervisor")), {})

            assert "agent-billing could not join" in caplog.text
            assert rooms[1].disconnects == 1
            assert sorted(gateway._by_agent) == ["supervisor", "tech_support"]
            assert gateway._active is gateway._participants[0]
            assert "'billing' has no participant of its own" in caplog.text
        finally:
            await gateway.stop()
            await task

    @pytest.mark.asyncio
    async def test_without_api_credentials_the_team_speaks_through_one_participant(self, monkeypatch, caplog):
        gateway, rooms = self._gateway(monkeypatch)
        task = await self._started(gateway)
        gateway._api_key = gateway._api_secret = None  # as with a token minted elsewhere
        try:
            with caplog.at_level(logging.WARNING):
                await self._announce(gateway, self.TEAM)

            assert len(rooms) == 1
            assert "needs 'api_key' and 'api_secret'" in caplog.text
        finally:
            await gateway.stop()
            await task

    @pytest.mark.asyncio
    async def test_a_listener_that_cannot_join_fails_the_start_and_leaves(self, monkeypatch):
        gateway, rooms = self._gateway(monkeypatch, fail_on=1)

        with pytest.raises(ConnectionError, match="join refused"):
            await gateway.start()

        assert [room.disconnects for room in rooms] == [1]
        assert gateway._sender_task is None

    @pytest.mark.asyncio
    async def test_nothing_waits_for_livekit_to_confirm_the_attributes(self, monkeypatch):
        """Regression: LiveKit confirms an attribute update only when the server does; startup used to
        wait on it and, unconfirmed, never finished until the room disconnected."""

        async def unconfirmed(self, attributes):
            await asyncio.Event().wait()

        monkeypatch.setattr(_LocalParticipant, "set_attributes", unconfirmed)
        gateway, rooms = self._gateway(monkeypatch)
        task = await self._started(gateway)
        try:
            await self._announce(gateway, self.TEAM)

            assert len(rooms) == 3
            assert len(gateway._background_tasks) == 3  # the unconfirmed attribute updates
        finally:
            await gateway.stop()
            await task

        await asyncio.sleep(0)
        assert gateway._background_tasks == set()

    @pytest.mark.asyncio
    async def test_a_stop_while_an_agent_is_joining_takes_it_out_too(self, monkeypatch):
        gateway, rooms = self._gateway(monkeypatch, hang_on=2)
        task = await self._started(gateway)
        await gateway.deliver_chunk(StreamChunk(event=AgentChanged(agent="supervisor", agents=self.TEAM)), {})
        await asyncio.sleep(0.05)

        await gateway.stop()
        await task

        assert [room.disconnects for room in rooms] == [1, 1, 1]

    @pytest.mark.asyncio
    async def test_one_room_dropping_ends_the_gateway_and_takes_every_participant_out(self, monkeypatch):
        gateway, rooms = self._gateway(monkeypatch)
        task = await self._started(gateway)
        await self._announce(gateway, self.TEAM)

        rooms[1].handlers["disconnected"]()
        await asyncio.wait_for(task, timeout=2)

        assert [room.disconnects for room in rooms] == [1, 1, 1]


class TestMultiAgentInbound:
    """Only the human is conversation input: no agent participant's audio or chat ever is."""

    def test_an_agent_participants_audio_is_unsubscribed_and_ignored(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _room_rtc())
        gateway = _gateway("supervisor", "billing")
        subscribed = []

        gateway._on_track_subscribed(
            types.SimpleNamespace(kind="audio"),
            types.SimpleNamespace(set_subscribed=subscribed.append),
            types.SimpleNamespace(identity="agent-billing"),
        )

        assert subscribed == [False]

    @pytest.mark.asyncio
    async def test_the_humans_audio_is_input(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _room_rtc())
        gateway = _gateway("supervisor", "billing")
        heard = []

        async def greet(identity):
            heard.append(("greet", identity))

        async def listen(track):
            heard.append(("audio", track))

        gateway._greet, gateway._process_incoming_audio = greet, listen
        track = types.SimpleNamespace(kind="audio")

        gateway._on_track_subscribed(track, types.SimpleNamespace(set_subscribed=None), types.SimpleNamespace(identity="caller"))
        await asyncio.sleep(0)

        assert heard == [("greet", "caller"), ("audio", track)]

    def test_an_agent_participants_chat_is_ignored(self, monkeypatch):
        gateway = _gateway("supervisor", "billing")
        seen = []
        monkeypatch.setattr(gateway, "_stage_request", seen.append)

        gateway._handle_chat_message(
            types.SimpleNamespace(topic="lk-chat", data=b"Billing here.", participant=types.SimpleNamespace(identity="agent-billing"))
        )
        gateway._handle_chat_message(_packet("hello"))

        assert [request.prompt for request in seen] == ["hello"]


class TestMultiAgentOutbound:
    """The agent speaking is heard and quoted through its own participant; the others stay silent."""

    @staticmethod
    def _audio():
        return StreamChunk(event=AudioDelta(message_id="m", content=base64.b64encode(b"\x00\x00").decode("utf-8")))

    @staticmethod
    def _text(text):
        return StreamChunk(event=TextDelta(message_id="m", content=text))

    @staticmethod
    def _change(agent, previous=None):
        return StreamChunk(event=AgentChanged(agent=agent, previous_agent=previous))

    @pytest.mark.asyncio
    async def test_each_agent_is_heard_and_quoted_through_its_own_participant(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        gateway = _gateway("supervisor", "billing", "tech_support")
        gateway._loop = asyncio.get_running_loop()
        supervisor, billing, tech_support = gateway._participants

        for chunk in [
            self._change("supervisor"),
            self._audio(),
            self._text("Connecting you."),
            StreamChunk(done=True),
            self._change("billing", "supervisor"),
            self._text("Billing here."),
            self._audio(),
            StreamChunk(done=True),
        ]:
            await gateway.deliver_chunk(chunk, {})
        await asyncio.sleep(0.05)

        assert [len(participant.audio_source.frames) for participant in (supervisor, billing, tech_support)] == [1, 1, 0]
        assert supervisor.room.local_participant.chat == ["Connecting you."]
        assert billing.room.local_participant.chat == ["Billing here."]
        # The supervisor's audio played out before billing was heard.
        assert supervisor.audio_source.playouts == 1
        assert [participant.room.local_participant.attributes for participant in (supervisor, billing)] == [
            {"ak.active": "false"},
            {"ak.active": "true"},
        ]
        # The agent with the call is unmuted; the one it took over from is muted, as is the third.
        assert [participant.track.muted for participant in (supervisor, billing, tech_support)] == [True, False, True]

    @pytest.mark.asyncio
    async def test_words_left_at_a_change_are_published_as_the_previous_agents(self):
        gateway = _gateway("supervisor", "billing")
        gateway._loop = asyncio.get_running_loop()

        await gateway.deliver_chunk(self._text("Let me check."), {})
        await gateway.deliver_chunk(self._change("billing", "supervisor"), {})

        assert gateway._participants[0].room.local_participant.chat == ["Let me check."]
        assert gateway._transcript == []

    @pytest.mark.asyncio
    async def test_a_change_does_not_wait_long_for_audio_that_will_not_play_out(self, monkeypatch, caplog):
        monkeypatch.setattr(LiveKitEdgeGateway, "PLAYOUT_WAIT_SECONDS", 0.05)
        gateway = _gateway("supervisor", "billing")
        gateway._loop = asyncio.get_running_loop()

        async def stuck():
            await asyncio.Event().wait()

        gateway._participants[0].audio_source.wait_for_playout = stuck

        with caplog.at_level(logging.WARNING):
            await asyncio.wait_for(gateway.deliver_chunk(self._change("billing", "supervisor"), {}), timeout=1)

        assert gateway._active is gateway._participants[1]
        assert "still playing" in caplog.text

    @pytest.mark.asyncio
    async def test_an_attribute_update_livekit_never_confirms_holds_up_no_audio(self, monkeypatch, caplog):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        monkeypatch.setattr(LiveKitEdgeGateway, "ATTRIBUTE_TIMEOUT_SECONDS", 0.05)
        gateway = _gateway("supervisor", "billing")
        gateway._loop = asyncio.get_running_loop()

        async def unconfirmed(attributes):
            await asyncio.Event().wait()

        for participant in gateway._participants:
            participant.room.local_participant.set_attributes = unconfirmed

        with caplog.at_level(logging.WARNING):
            await asyncio.wait_for(gateway.deliver_chunk(self._change("billing", "supervisor"), {}), timeout=1)
            await asyncio.wait_for(gateway.deliver_chunk(self._audio(), {}), timeout=1)
            await asyncio.sleep(0.2)

        assert len(gateway._participants[1].audio_source.frames) == 1
        assert caplog.text.count("did not confirm") == 2

    @pytest.mark.asyncio
    async def test_an_interrupt_silences_every_agent_participant(self):
        gateway = _gateway("supervisor", "billing")
        gateway._loop = asyncio.get_running_loop()

        await gateway.deliver_chunk(StreamChunk(event=Interrupt()), {})
        await asyncio.sleep(0)

        assert [participant.audio_source.clears for participant in gateway._participants] == [1, 1]

    @pytest.mark.asyncio
    async def test_a_handoff_to_an_agent_still_joining_is_noted_not_warned(self, caplog):
        """Normal in the first second of a call: no warning is spent on it, so one is left if the join
        then fails."""
        gateway = _gateway("supervisor", "billing")
        gateway._loop = asyncio.get_running_loop()
        del gateway._by_agent["billing"]
        gateway._joining.add("billing")

        with caplog.at_level(logging.INFO):
            await gateway.deliver_chunk(self._change("billing", "supervisor"), {})

        assert "'billing' is still joining the room" in caplog.text
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
        assert gateway._warned_agents == set()

    @pytest.mark.asyncio
    async def test_an_agent_without_a_participant_speaks_through_the_first(self, caplog):
        gateway = _gateway("supervisor", "billing")
        gateway._loop = asyncio.get_running_loop()
        await gateway.deliver_chunk(self._change("billing", "supervisor"), {})

        with caplog.at_level(logging.WARNING):
            await gateway.deliver_chunk(self._change("sales", "billing"), {})
            await gateway.deliver_chunk(self._change("billing", "sales"), {})
            await gateway.deliver_chunk(self._change("sales", "billing"), {})

        assert gateway._active is gateway._participants[0]
        assert caplog.text.count("'sales' has no participant of its own") == 1

    @pytest.mark.asyncio
    async def test_an_agent_handed_to_while_joining_moves_to_its_own_participant_once_in(self, monkeypatch):
        """The handoff falls back to the first participant while billing joins; once billing is in,
        its next output goes through its own participant, unmuted, with the first one muted."""
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        gateway = _gateway("supervisor", "billing")
        gateway._loop = asyncio.get_running_loop()
        supervisor, billing = gateway._participants
        del gateway._by_agent["billing"]  # still joining

        await gateway.deliver_chunk(self._change("billing", "supervisor"), {})
        await gateway.deliver_chunk(self._audio(), {})
        assert gateway._active is supervisor

        gateway._by_agent["billing"] = billing  # the join completes
        await gateway.deliver_chunk(self._audio(), {})
        await asyncio.sleep(0.05)

        assert gateway._active is billing
        assert [len(supervisor.audio_source.frames), len(billing.audio_source.frames)] == [1, 1]
        assert [supervisor.track.muted, billing.track.muted] == [True, False]

    @pytest.mark.asyncio
    async def test_a_single_participant_speaks_for_every_agent(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        gateway = _gateway()
        gateway._loop = asyncio.get_running_loop()

        await gateway.deliver_chunk(self._change("billing", "supervisor"), {})
        await gateway.deliver_chunk(self._audio(), {})

        assert gateway._active is gateway._participants[0]
        assert len(gateway._active.audio_source.frames) == 1
        assert gateway._active.room.local_participant.attributes == {}
        assert gateway._active.track.muted is False


class _Recorder(LiveKitEdgeGateway):
    """A gateway whose three hooks record what they were called with, in order, and where they ran."""

    @classmethod
    def build(cls, *agents) -> "_Recorder":
        gateway = _gateway(*agents)
        gateway.__class__ = cls
        gateway.calls = []
        gateway.threads = []
        return gateway

    def on_transcript(self, line):
        self.threads.append(threading.current_thread().name)
        self.calls.append(("line", line))

    def on_agent_changed(self, agent, previous):
        self.calls.append(("changed", agent, previous))

    def on_error(self, message):
        self.calls.append(("error", message))


def _audio():
    return StreamChunk(event=AudioDelta(message_id="m", content=base64.b64encode(b"\x00\x00").decode("utf-8")))


def _text(text, message_id="m"):
    return StreamChunk(event=TextDelta(message_id=message_id, content=text))


def _change(agent, previous=None, agents=None):
    return StreamChunk(event=AgentChanged(agent=agent, previous_agent=previous, agents=agents))


def _heard(text, message_id="i1"):
    return StreamChunk(event=InputTranscript(message_id=message_id, content=text))


def _lines(gateway):
    gateway._close_hooks()
    return [(call[1].speaker, call[1].role, call[1].text, call[1].interrupted) for call in gateway.calls if call[0] == "line"]


class TestTranscriptHooks:
    @pytest.mark.asyncio
    async def test_lines_and_speaker_changes_arrive_in_order_across_a_handoff(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        gateway = _Recorder.build("pm", "ba")
        gateway._loop = asyncio.get_running_loop()
        gateway._caller_identity = "client-1"

        for chunk in [
            _change("pm"),
            _text("Hello. "),
            _text("What do you need?"),
            _change("ba", "pm"),
            _text("BA here."),
            StreamChunk(done=True),
            _heard("a booking system"),
        ]:
            await gateway.deliver_chunk(chunk, {})
        gateway._close_hooks()

        kinds = [(call[0], *([call[1].speaker, call[1].text] if call[0] == "line" else call[1:])) for call in gateway.calls]
        assert kinds == [
            ("changed", "pm", None),
            ("line", "pm", "Hello. What do you need?"),
            ("changed", "ba", "pm"),
            ("line", "ba", "BA here."),
            ("line", "client-1", "a booking system"),
        ]
        roles = [call[1].role for call in gateway.calls if call[0] == "line"]
        assert roles == ["agent", "agent", "user"]
        assert all(name.startswith("edge-hooks-s1") for name in gateway.threads)

    def test_a_typed_chat_message_is_one_typed_user_line_and_is_still_staged(self, monkeypatch):
        gateway = _Recorder.build("pm", "ba")
        staged = []
        monkeypatch.setattr(gateway, "_stage_request", staged.append)

        gateway._handle_chat_message(_packet('{"message": "half of all bookings online"}'))
        gateway._close_hooks()

        assert [request.prompt for request in staged] == ["half of all bookings online"]
        [(kind, line)] = gateway.calls
        assert kind == "line"
        assert (line.speaker, line.role, line.text, line.typed) == ("human", "user", "half of all bookings online", True)
        assert line.interrupted is False and line.at > 0

    def test_an_agent_participants_chat_gives_no_line(self, monkeypatch):
        gateway = _Recorder.build("pm", "ba")
        monkeypatch.setattr(gateway, "_stage_request", lambda request: None)

        gateway._handle_chat_message(types.SimpleNamespace(topic="lk-chat", data=b"BA here.", participant=types.SimpleNamespace(identity="agent-ba")))
        gateway._close_hooks()

        assert gateway.calls == []

    def test_a_spoken_line_is_not_typed(self):
        assert TranscriptLine(speaker="client", role="user", text="hi", at=1.0).typed is False

    @pytest.mark.asyncio
    async def test_a_single_participant_gateway_still_splits_lines_at_a_handoff(self):
        gateway = _Recorder.build()
        gateway._loop = asyncio.get_running_loop()

        for chunk in [_change("pm"), _text("One."), _change("ba", "pm"), _text("Two."), StreamChunk(done=True)]:
            await gateway.deliver_chunk(chunk, {})

        assert _lines(gateway) == [("pm", "agent", "One.", False), ("ba", "agent", "Two.", False)]
        # The chat text is not split at the handoff: it is one message at the end of the turn.
        assert gateway._participants[0].room.local_participant.chat == ["One.Two."]

    @pytest.mark.asyncio
    async def test_the_previous_agent_falls_back_to_the_one_that_was_speaking(self):
        gateway = _Recorder.build("pm", "ba")
        gateway._loop = asyncio.get_running_loop()

        await gateway.deliver_chunk(_change("pm"), {})
        await gateway.deliver_chunk(_change("ba"), {})
        gateway._close_hooks()

        assert [call for call in gateway.calls if call[0] == "changed"] == [("changed", "pm", None), ("changed", "ba", "pm")]

    @pytest.mark.asyncio
    async def test_an_interrupted_line_carries_what_was_delivered_and_nothing_after_it(self):
        gateway = _Recorder.build("pm")
        gateway._loop = asyncio.get_running_loop()

        for chunk in [_change("pm"), _text("I was about to"), StreamChunk(event=Interrupt()), _text(" never delivered"), StreamChunk(done=True)]:
            await gateway.deliver_chunk(chunk, {})

        assert _lines(gateway) == [("pm", "agent", "I was about to", True)]

    @pytest.mark.asyncio
    async def test_the_caller_is_named_user_before_any_track_has_been_seen(self):
        gateway = _Recorder.build("pm")
        gateway._loop = asyncio.get_running_loop()

        await gateway.deliver_chunk(_heard("hi"), {})

        assert _lines(gateway) == [("user", "user", "hi", False)]

    @pytest.mark.asyncio
    async def test_an_error_chunk_flushes_the_partial_line_then_calls_on_error(self):
        gateway = _Recorder.build("pm")
        gateway._loop = asyncio.get_running_loop()

        for chunk in [_change("pm"), _text("Half a"), StreamChunk(error="model failed", done=True)]:
            await gateway.deliver_chunk(chunk, {})
        gateway._close_hooks()

        assert [call[0] for call in gateway.calls] == ["changed", "line", "error"]
        assert gateway.calls[1][1].interrupted is True
        assert gateway.calls[2] == ("error", "model failed")
        assert gateway._participants[0].room.local_participant.chat == ["model failed"]

    @pytest.mark.asyncio
    async def test_deliver_error_called_directly_also_calls_on_error(self):
        gateway = _Recorder.build("pm")
        gateway._loop = asyncio.get_running_loop()

        await gateway.deliver_error("permanent failure", {})
        gateway._close_hooks()

        assert gateway.calls == [("error", "permanent failure")]

    @pytest.mark.asyncio
    async def test_a_raising_hook_does_not_stop_delivery_or_the_next_hook(self, monkeypatch, caplog):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        gateway = _Recorder.build("pm")
        gateway._loop = asyncio.get_running_loop()

        def explode(line):
            raise RuntimeError("hook bug")

        gateway.on_transcript = explode
        with caplog.at_level(logging.ERROR, logger="ak.integration.edge_hooks"):
            for chunk in [_change("pm"), _audio(), _text("Hello."), StreamChunk(done=True), _audio()]:
                await gateway.deliver_chunk(chunk, {})
            gateway._close_hooks()

        assert len(gateway._participants[0].audio_source.frames) == 2
        assert gateway._participants[0].room.local_participant.chat == ["Hello."]
        assert [call[0] for call in gateway.calls] == ["changed"]
        assert "hook bug" in caplog.text


class TestCaptions:
    @pytest.mark.asyncio
    async def test_an_agents_deltas_stream_on_its_participant_and_end_with_one_final_message(self):
        gateway = _gateway("pm", "ba")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        pm, ba = gateway._participants

        for chunk in [_change("pm"), _text("Hello "), _text("there."), StreamChunk(done=True)]:
            await gateway.deliver_chunk(chunk, {})
        await gateway._drain_captions(1)

        [stream] = pm.room.local_participant.streams
        assert stream.topic == "lk.transcription"
        assert stream.sender_identity == "agent-pm"
        assert stream.written == ["Hello ", "there."]
        assert stream.closed
        assert stream.attributes["lk.transcribed_track_id"] == "TR_agent-pm"
        assert stream.attributes["lk.transcription_final"] == "false"
        [final] = pm.room.local_participant.texts
        assert final["text"] == "Hello there."
        assert final["topic"] == "lk.transcription"
        assert final["attributes"]["lk.segment_id"] == stream.attributes["lk.segment_id"]
        assert final["attributes"]["lk.transcription_final"] == "true"
        assert ba.room.local_participant.streams == []
        # The turn-end chat message is unchanged.
        assert pm.room.local_participant.chat == ["Hello there."]

    @pytest.mark.asyncio
    async def test_each_boundary_ends_a_segment_and_the_next_one_gets_its_own_id(self):
        gateway = _gateway("pm", "ba")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        pm, ba = gateway._participants

        for chunk in [
            _change("pm"),
            _text("One."),
            _change("ba", "pm"),
            _text("Two."),
            StreamChunk(done=True),
            _text("Three."),
            StreamChunk(event=Interrupt()),
        ]:
            await gateway.deliver_chunk(chunk, {})
        await gateway._drain_captions(1)

        assert [stream.written for stream in pm.room.local_participant.streams] == [["One."]]
        assert [stream.written for stream in ba.room.local_participant.streams] == [["Two."], ["Three."]]
        assert [text["text"] for text in ba.room.local_participant.texts] == ["Two.", "Three."]
        ids = {stream.attributes["lk.segment_id"] for participant in (pm, ba) for stream in participant.room.local_participant.streams}
        assert len(ids) == 3
        # The speaking participant's own track is what each caption is attributed to.
        assert {stream.attributes["lk.transcribed_track_id"] for stream in ba.room.local_participant.streams} == {"TR_agent-ba"}

    @pytest.mark.asyncio
    async def test_an_interrupted_segment_ends_with_what_was_delivered(self):
        gateway = _gateway("pm")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()

        for chunk in [_text("Almost"), StreamChunk(event=Interrupt()), _text(" lost"), StreamChunk(done=True)]:
            await gateway.deliver_chunk(chunk, {})
        await gateway._drain_captions(1)

        participant = gateway._participants[0].room.local_participant
        assert [text["text"] for text in participant.texts] == ["Almost"]
        assert [stream.written for stream in participant.streams] == [["Almost"]]

    @pytest.mark.asyncio
    async def test_the_callers_line_is_a_final_caption_attributed_to_the_caller(self):
        gateway = _gateway("pm", "ba")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        gateway._caller_identity = "client-1"
        gateway._caller_track_sid = "TR_client"

        await gateway.deliver_chunk(_heard("we need booking"), {})
        await gateway._drain_captions(1)

        [stream] = gateway._participants[0].room.local_participant.streams
        assert stream.sender_identity == "client-1"
        assert stream.topic == "lk.transcription"
        assert stream.written == ["we need booking"]
        assert stream.attributes["lk.transcribed_track_id"] == "TR_client"
        assert stream.attributes["lk.transcription_final"] == "true"

    @pytest.mark.asyncio
    async def test_a_failing_stream_logs_once_per_segment_and_never_stops_audio_or_chat(self, caplog):
        gateway = _gateway("pm")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        participant = gateway._participants[0]

        async def broken(**kwargs):
            raise RuntimeError("no stream")

        participant.room.local_participant.stream_text = broken
        with caplog.at_level(logging.WARNING, logger="ak.integration.livekit"):
            for chunk in [
                _text("One "),
                _text("two "),
                _text("three."),
                StreamChunk(done=True),
                _text("Next "),
                _text("segment."),
                StreamChunk(done=True),
            ]:
                await gateway.deliver_chunk(chunk, {})
            await gateway._drain_captions(1)

        assert participant.room.local_participant.chat == ["One two three.", "Next segment."]
        assert participant.room.local_participant.texts == []
        assert caplog.text.count("Caption stream failed") == 2  # one per segment, not one per delta

    @pytest.mark.asyncio
    async def test_a_blocked_caption_write_does_not_block_delivery_and_captions_arrive_in_order(self):
        gateway = _gateway("pm")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        participant = gateway._participants[0]
        gate = asyncio.Event()
        original = participant.room.local_participant.stream_text

        async def slow(**kwargs):
            await gate.wait()
            return await original(**kwargs)

        participant.room.local_participant.stream_text = slow
        chunks = [_text("Hello "), _text("there."), StreamChunk(done=True), _heard("hi")]

        for chunk in chunks:
            await asyncio.wait_for(gateway.deliver_chunk(chunk, {}), 1)  # returns although the stream cannot open yet

        assert participant.room.local_participant.streams == []
        assert participant.room.local_participant.chat == ["Hello there."]  # the chat message does not wait either
        gate.set()
        await gateway._drain_captions(2)

        streams = participant.room.local_participant.streams
        assert [stream.written for stream in streams] == [["Hello ", "there."], ["hi"]]
        assert [text["text"] for text in participant.room.local_participant.texts] == ["Hello there."]
        assert streams[0].attributes["lk.transcription_final"] == "false" and streams[1].attributes["lk.transcription_final"] == "true"

    @pytest.mark.asyncio
    async def test_release_drains_the_caption_queue_and_stops_the_task(self):
        gateway = _gateway("pm")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        task = gateway._caption_task
        await gateway.deliver_chunk(_text("Bye."), {})
        await gateway.deliver_chunk(StreamChunk(done=True), {})

        await gateway._release()

        assert task.done() and gateway._caption_task is None

    @pytest.mark.asyncio
    async def test_release_cancels_a_caption_task_stuck_past_the_drain_time(self, monkeypatch, caplog):
        monkeypatch.setattr(LiveKitEdgeGateway, "CAPTION_DRAIN_SECONDS", 0.05)
        gateway = _gateway("pm")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        task = gateway._caption_task

        async def stuck(**kwargs):
            await asyncio.Event().wait()

        gateway._participants[0].room.local_participant.stream_text = stuck
        await gateway.deliver_chunk(_text("Never opens."), {})
        await asyncio.sleep(0.02)
        with caplog.at_level(logging.WARNING, logger="ak.integration.livekit"):
            await asyncio.wait_for(gateway._release(), 2)

        assert task.done() and "not all sent" in caplog.text

    @pytest.mark.asyncio
    async def test_a_participant_with_no_track_yet_skips_the_caption_but_keeps_the_line(self):
        gateway = _Recorder.build("pm")
        gateway._loop = asyncio.get_running_loop()
        gateway._start_captions()
        gateway._participants[0].track = None

        for chunk in [_change("pm"), _text("Early words."), StreamChunk(done=True)]:
            await gateway.deliver_chunk(chunk, {})

        assert gateway._participants[0].room.local_participant.streams == []
        assert _lines(gateway) == [("pm", "agent", "Early words.", False)]


class TestOpeningPrompt:
    @staticmethod
    def _staged(gateway):
        gateway._producer = object()
        gateway._pending = asyncio.Queue()
        return gateway._pending

    @pytest.mark.asyncio
    async def test_the_default_is_the_fixed_hello_word_for_word(self):
        gateway = _gateway("pm")
        pending = self._staged(gateway)

        await gateway._greet("human-1")

        [staged] = [pending.get_nowait()]
        assert staged.requests[0].prompt == (
            "A user named human-1 just connected their microphone. Say a very short hello to them and confirm you are connected!"
        )

    @pytest.mark.asyncio
    async def test_none_stages_nothing(self):
        gateway = _gateway("pm")
        gateway.opening_prompt = lambda identity: None
        pending = self._staged(gateway)

        await gateway._greet("human-1")

        assert pending.empty()

    @pytest.mark.asyncio
    async def test_a_custom_prompt_is_sent_once_per_subscription(self):
        gateway = _gateway("pm")
        gateway.opening_prompt = lambda identity: f"Open the meeting for {identity}."
        pending = self._staged(gateway)

        await gateway._greet("human-1")

        assert pending.qsize() == 1
        assert pending.get_nowait().requests[0].prompt == "Open the meeting for human-1."

    def test_the_callers_identity_and_track_are_recorded_on_subscribe(self, monkeypatch):
        gateway = _gateway("pm", "ba")
        monkeypatch.setattr(livekit_adapter.asyncio, "create_task", lambda coro: coro.close())
        monkeypatch.setattr(livekit_adapter, "rtc", types.SimpleNamespace(TrackKind=types.SimpleNamespace(KIND_AUDIO=1)))
        track = types.SimpleNamespace(kind=1, sid="TR_mic")

        gateway._on_track_subscribed(track, types.SimpleNamespace(sid="TR_pub"), types.SimpleNamespace(identity="client-9"))

        assert gateway._caller_identity == "client-9"
        assert gateway._caller_track_sid == "TR_pub"


class TestSessionEnd:
    @pytest.mark.asyncio
    async def test_release_sends_one_control_after_the_pending_frames(self):
        gateway = _gateway("pm")
        gateway._connected = True
        gateway._loop = asyncio.get_running_loop()
        producer = _Producer()
        gateway._producer = producer
        gateway._pending = asyncio.Queue()
        gateway._sender_task = asyncio.create_task(gateway._drain_requests())
        gateway._stage_request(AgentRequestText(prompt="last words"))
        gateway._stage_request(AgentRequestText(prompt="more"))

        await gateway._release()
        await gateway._release()

        prompts = [[request.prompt for request in call["request"].requests] for call in producer.calls]
        assert prompts == [["last words"], ["more"], []]
        assert [call["attributes"] for call in producer.calls] == [None, None, {"realtime_end": "true"}]
        assert producer.calls[-1]["request"].session_id == "s1"

    @pytest.mark.asyncio
    async def test_a_hook_that_never_returns_cannot_hold_up_release(self, monkeypatch):
        gateway = _Recorder.build("pm")
        gateway._connected = True
        gateway._loop = asyncio.get_running_loop()
        gateway._producer = _Producer()
        gateway._pending = asyncio.Queue()
        monkeypatch.setattr(gateway, "HOOKS_CLOSE_TIMEOUT_SECONDS", 0.2)
        stuck, entered = threading.Event(), threading.Event()

        def block(line):
            entered.set()
            stuck.wait()

        gateway._dispatch_hook(block, TranscriptLine(speaker="pm", role="agent", text="hi", at=1.0))
        assert await asyncio.to_thread(entered.wait, 5)

        try:
            await asyncio.wait_for(gateway._release(), timeout=3)
        finally:
            stuck.set()

    @pytest.mark.asyncio
    async def test_frames_after_the_end_are_not_staged(self):
        gateway = _gateway("pm")
        gateway._connected = True
        gateway._producer = _Producer()
        gateway._pending = asyncio.Queue()
        gateway._sender_task = asyncio.create_task(gateway._drain_requests())

        await gateway._release()
        gateway._stage_request(AgentRequestText(prompt="late"))

        assert gateway._pending.empty()

    @pytest.mark.asyncio
    async def test_a_gateway_that_never_connected_sends_no_control(self):
        gateway = _gateway("pm")
        gateway._producer = _Producer()

        await gateway._release()

        assert gateway._producer.calls == []

    @pytest.mark.asyncio
    async def test_a_failing_control_is_logged_and_release_still_leaves_the_room(self, caplog):
        gateway = _gateway("pm")
        gateway._connected = True

        class _Broken:
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("broker down")

        gateway._producer = _Broken()
        participant = gateway._participants[0]
        room = participant.room
        with caplog.at_level(logging.WARNING, logger="ak.integration.livekit"):
            await gateway._release()

        assert "broker down" in caplog.text
        assert room.disconnects == 1

    @pytest.mark.asyncio
    async def test_start_marks_the_edge_ready_once_connected(self, monkeypatch):
        _config(monkeypatch)
        gateway = LiveKitEdgeGateway(session_id="room-r")

        class _Room2(_Room):
            async def connect(self, url, token, options):
                self.options = options

        class _RtcStub:
            RoomOptions = staticmethod(lambda **kwargs: kwargs)
            TrackSource = types.SimpleNamespace(SOURCE_MICROPHONE=2)
            TrackPublishOptions = staticmethod(lambda **kwargs: kwargs)
            AudioSource = staticmethod(lambda **kwargs: _AudioSource())
            LocalAudioTrack = types.SimpleNamespace(create_audio_track=staticmethod(lambda name, source: _Track(name)))
            Room = _Room2

        monkeypatch.setattr(livekit_adapter, "rtc", _RtcStub)
        monkeypatch.setattr(gateway, "_init_producer", lambda: setattr(gateway, "_producer", _Producer()))
        task = asyncio.create_task(gateway.start())
        for _ in range(100):
            if gateway.wait_ready(0):
                break
            await asyncio.sleep(0.01)

        assert gateway.wait_ready(0)
        await gateway.stop()
        await asyncio.wait_for(task, 5)
