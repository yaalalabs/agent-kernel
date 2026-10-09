"""Focused tests for the LiveKit edge gateway with the SDK boundary stubbed.

The real ``rtc``/``Room`` stack needs a live WebRTC connection, so these tests exercise the
gateway's own logic (audio batching into the input queue, chat parsing, outbound playback,
barge-in, and transcript publication) against simple fakes.
"""

import asyncio
import base64
import json
import logging
import types

import pytest

import agentkernel.integration.livekit.adapter as livekit_adapter
from agentkernel.core.event import AgentChanged, AudioDelta, Interrupt, TextDelta
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


class _LocalParticipant:
    def __init__(self, identity=None):
        self.identity = identity
        self.attributes = {}
        self.chat = []
        self.tracks = []

    async def publish_track(self, track, options):
        self.tracks.append(track)

    async def set_attributes(self, attributes):
        self.attributes.update(attributes)

    async def publish_data(self, payload, reliable=True, topic=""):
        self.chat.append(json.loads(payload)["message"])


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
    gateway._background_tasks = set()
    gateway._transcript = []
    gateway._interrupted = False
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
