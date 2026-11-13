"""Focused tests for the LiveKit edge with the SDK boundary stubbed.

The real ``rtc``/``Room`` stack needs a live WebRTC connection, so these tests exercise the
edge's own logic (audio batching into the input queue, chat parsing, outbound playback,
barge-in, and transcript publication) against simple fakes.
"""

import asyncio
import base64
import json
import logging
import threading
import types
from types import SimpleNamespace

import pytest

import agentkernel.integration.livekit.adapter as livekit_adapter
from agentkernel.core.event import AgentChanged, AudioDelta, InputTranscript, Interrupt, TextDelta
from agentkernel.core.model import AgentRequestText, AgentRequestVoice, StreamChunk
from agentkernel.integration.adapter.base import Source
from agentkernel.integration.livekit.adapter import LiveKitEdgeAdapter


class _FakeRtc:
    @staticmethod
    def AudioFrame(**kwargs):
        return types.SimpleNamespace(**kwargs)


class _Producer:
    def __init__(self):
        self.calls = []

    def enqueue(self, adapter_name, request, source=None):
        self.calls.append({"adapter_name": adapter_name, "request": request, "source": source})


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
    participant = LiveKitEdgeAdapter._AgentParticipant(agent, identity, "token")
    participant.room = _Room(identity)
    participant.audio_source = _AudioSource()
    participant.track = _Track()
    participant.track.sid = f"TR_{identity}"
    participant.track.muted = muted
    return participant


def _edge(*agents) -> LiveKitEdgeAdapter:
    """Build an edge without the constructor's config/token work: one participant per agent named,
    or a single participant speaking for every agent."""
    edge = object.__new__(LiveKitEdgeAdapter)
    edge.session_id = "s1"
    edge.room_url = "wss://lk"
    edge.agent = "general"
    edge._api_key, edge._api_secret = "key", "secret" * 8
    edge._producer = None
    edge._pending = None
    edge._sender_task = None
    edge._loop = None
    edge._stop_event = None
    # As in a room: the first participant is heard, every other one is muted.
    edge._participants = [_participant(agent, f"agent-{agent}", muted=index > 0) for index, agent in enumerate(agents)] or [_participant()]
    edge._by_agent = {participant.agent: participant for participant in edge._participants if participant.agent}
    edge._own_identities = {participant.identity for participant in edge._participants}
    edge._active = edge._participants[0]
    edge._joining = set()
    edge._warned_agents = set()
    edge._greeted = set()
    edge._speaking_agent = None
    edge._background_tasks = set()
    edge._transcript = []
    edge._interrupted = False
    edge._end_sent = False
    edge._connected = False
    edge._ready = threading.Event()
    edge.name = "livekit"
    edge._input_batch_ms = 100
    edge._input_batch_bytes = 4800
    return edge


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

        edge = LiveKitEdgeAdapter(agent_name=agent_name, session_id="room-1")

        claims = self._claims(edge.token)
        assert claims["sub"] == identity
        assert claims["video"]["room"] == "room-1"
        assert edge.agent == agent_name

    def test_an_announced_agent_gets_a_token_of_its_own(self, monkeypatch):
        _config(monkeypatch)
        edge = LiveKitEdgeAdapter(agent_name="supervisor", session_id="room-1")

        claims = self._claims(edge._mint_token("billing"))

        assert claims["sub"] == "agent-billing"
        assert claims["name"] == "billing Agent"
        assert claims["video"]["room"] == "room-1"
        # Lets the participant set its ak.active attribute.
        assert claims["video"]["canUpdateOwnMetadata"] is True


class TestInboundStaging:
    @pytest.mark.asyncio
    async def test_enqueue_stages_and_the_sender_delivers_to_the_producer(self):
        edge = _edge()
        edge._api_key = "lk-key"
        edge._producer = _Producer()
        edge._pending = asyncio.Queue(maxsize=4)
        sender = asyncio.create_task(edge._drain_requests())
        try:
            edge._stage_request(AgentRequestText(prompt="hi"), "human")
            for _ in range(50):
                if edge._producer.calls:
                    break
                await asyncio.sleep(0.01)
        finally:
            sender.cancel()

        [call] = edge._producer.calls
        assert call["adapter_name"] == "livekit"
        assert call["request"].session_id == "s1"
        assert call["request"].agent == "general"
        assert call["request"].reply_context == {"session_id": "s1"}
        # The participant LiveKit asserts is the subject, the API key id its scope, and the edge
        # tells the producer it is a realtime source so the principal gets the realtime prefix (#603).
        assert (call["request"].user_id, call["request"].namespace) == ("human", "lk-key")
        assert call["source"] == Source.REALTIME

    def test_enqueue_carries_no_agent_when_none_is_configured(self):
        edge = _edge()
        edge.agent = None

        assert edge._enqueue(AgentRequestText(prompt="hi")).agent is None

    def test_integration_producer_stamps_the_configured_agent_on_the_queued_body(self):
        from agentkernel.integration.adapter.producer import IntegrationProducer

        sent = []
        producer = object.__new__(IntegrationProducer)
        producer._producer = types.SimpleNamespace(enqueue=lambda body, **kwargs: sent.append((body, kwargs)))
        edge = _edge()

        producer.enqueue(edge.name, edge._enqueue(AgentRequestText(prompt="hi")))

        [(body, kwargs)] = sent
        assert body.agent == "general"
        assert body.session_id == "s1"
        assert kwargs["group_id"] == "s1"
        assert kwargs["attributes"]["integration"] == "livekit"
        assert kwargs["attributes"]["reply_session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_enqueue_drops_a_frame_when_the_staging_queue_is_full(self, caplog):
        edge = _edge()
        edge._producer = _Producer()
        edge._pending = asyncio.Queue(maxsize=1)
        edge._pending.put_nowait("staged")

        with caplog.at_level(logging.WARNING):
            edge._stage_request(AgentRequestText(prompt="hi"))

        assert edge._pending.qsize() == 1
        assert any("full" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_chat_message_parses_json_and_plain_text(self, monkeypatch):
        edge = _edge()
        seen = []
        monkeypatch.setattr(edge, "_stage_request", lambda request, participant_identity=None: seen.append((request, participant_identity)))

        edge._handle_chat_message(_packet('{"message": "hello"}'))
        edge._handle_chat_message(_packet("plain text", topic="chat"))
        edge._handle_chat_message(_packet("ignored", topic="some-other-topic"))

        assert [request.prompt for request, _ in seen] == ["hello", "plain text"]
        # The packet's sender is the participant the request runs as (#603).
        assert [identity for _, identity in seen] == ["human", "human"]


class TestInboundAudioBatching:
    @pytest.mark.asyncio
    async def test_pass_through_enqueues_every_frame_when_batch_is_zero(self, monkeypatch):
        frames = [b"\x01\x02", b"\x03\x04", b"\x05\x06"]
        monkeypatch.setattr(livekit_adapter, "rtc", _fake_rtc(frames))
        edge = _edge()
        edge._input_batch_bytes = 0
        seen = []
        edge._stage_request = lambda request, participant_identity=None: seen.append((request, participant_identity))

        await edge._process_incoming_audio(object(), "human")

        assert [base64.b64decode(request.audio_data) for request, _ in seen] == frames
        # Every frame is staged as the participant whose track it came from (#603).
        assert {identity for _, identity in seen} == {"human"}

    @pytest.mark.asyncio
    async def test_batches_frames_to_the_configured_size_and_flushes_the_tail(self, monkeypatch):
        frames = [b"\x00" * 3, b"\x00" * 3, b"\x00" * 3, b"\x00" * 2]
        monkeypatch.setattr(livekit_adapter, "rtc", _fake_rtc(frames))
        edge = _edge()
        edge._input_batch_bytes = 6
        seen = []
        edge._stage_request = lambda request, participant_identity=None: seen.append(request)

        await edge._process_incoming_audio(object())

        assert [len(base64.b64decode(request.audio_data)) for request in seen] == [6, 5]

    def test_enqueue_audio_base64_encodes_a_voice_request(self):
        edge = _edge()
        seen = []
        edge._stage_request = lambda request, participant_identity=None: seen.append(request)

        edge._stage_request(edge._enqueue_audio(b"\x01\x02\x03\x04"))

        [request] = seen
        assert isinstance(request, AgentRequestVoice)
        assert request.audio_data == base64.b64encode(b"\x01\x02\x03\x04").decode("utf-8")


class TestOutboundDelivery:
    @pytest.mark.asyncio
    async def test_audio_delta_is_played_immediately(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        edge = _edge()
        source = edge._active.audio_source
        edge._loop = asyncio.get_running_loop()

        audio = base64.b64encode(b"\x00\x00" * 10).decode("utf-8")
        await edge.deliver_chunk(StreamChunk(event=AudioDelta(message_id="m", content=audio)), {})

        assert len(source.frames) == 1
        assert source.frames[0].samples_per_channel == 10

    @pytest.mark.asyncio
    async def test_transcript_is_accumulated_and_published_on_done(self, monkeypatch):
        edge = _edge()
        published = []

        async def fake_publish(text):
            published.append(text)

        monkeypatch.setattr(edge, "_publish_text", fake_publish)

        await edge.deliver_chunk(StreamChunk(event=TextDelta(message_id="m", content="Hello ")), {})
        await edge.deliver_chunk(StreamChunk(event=TextDelta(message_id="m", content="world")), {})
        await edge.deliver_chunk(StreamChunk(done=True), {})

        assert published == ["Hello world"]
        assert edge._transcript == []

    @pytest.mark.asyncio
    async def test_interrupt_clears_playback_and_drops_the_partial_transcript(self, monkeypatch):
        edge = _edge()
        source = edge._active.audio_source
        edge._loop = asyncio.get_running_loop()

        published = []
        monkeypatch.setattr(edge, "_publish_text", lambda text: published.append(text))

        await edge.deliver_chunk(StreamChunk(event=TextDelta(message_id="m", content="half")), {})
        await edge.deliver_chunk(StreamChunk(event=Interrupt()), {})
        await asyncio.sleep(0)  # let the loop run the marshalled clear_queue callback
        await edge.deliver_chunk(StreamChunk(done=True), {})

        assert source.clears == 1
        assert published == []  # the interrupted sentence is never published
        assert edge._interrupted is False

    @pytest.mark.asyncio
    async def test_the_turn_after_an_interrupted_one_is_published(self, monkeypatch):
        """The interrupted turn's done resets the state, so the next turn is published normally."""
        edge = _edge()
        edge._loop = asyncio.get_running_loop()

        published = []

        async def fake_publish(text):
            published.append(text)

        monkeypatch.setattr(edge, "_publish_text", fake_publish)

        await edge.deliver_chunk(StreamChunk(event=TextDelta(message_id="m1", content="cut off")), {})
        await edge.deliver_chunk(StreamChunk(event=Interrupt()), {})
        await edge.deliver_chunk(StreamChunk(done=True), {})
        await edge.deliver_chunk(StreamChunk(event=TextDelta(message_id="m2", content="next answer")), {})
        await edge.deliver_chunk(StreamChunk(done=True), {})

        assert published == ["next answer"]


def _room_rtc(fail_on=None, hang_on=None):
    """Stands in for ``livekit.rtc`` while an edge joins the room; ``rooms`` lists every room it opened.
    The ``fail_on``-th room refuses to connect; the ``hang_on``-th never finishes connecting."""
    rooms = []

    def room():
        opened = _Room()
        opened.remote_participants = {"PA_caller": types.SimpleNamespace(identity="caller-1")}
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
    """The edge starts as the one participant that hears the human; the team the conversation
    announces joins as participants of their own, each with its own track, with nothing configured."""

    TEAM = ["supervisor", "billing", "tech_support"]

    @staticmethod
    def _edge(monkeypatch, **rtc_options):
        _config(monkeypatch)
        rtc = _room_rtc(**rtc_options)
        monkeypatch.setattr(livekit_adapter, "rtc", rtc)
        monkeypatch.setattr(LiveKitEdgeAdapter, "_init_producer", lambda self: None)
        return LiveKitEdgeAdapter(agent_name="supervisor", session_id="room-1"), rtc.rooms

    @staticmethod
    async def _started(edge):
        task = asyncio.create_task(edge.start())
        for _ in range(100):
            if edge._connected or task.done():
                break
            await asyncio.sleep(0.01)
        return task

    @staticmethod
    async def _announce(edge, agents):
        """Deliver the conversation's opening AgentChanged, then let the joins and attribute updates land."""
        await edge.deliver_chunk(StreamChunk(event=AgentChanged(agent="supervisor", agents=agents)), {})
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not edge._joining:
                break
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_the_edge_starts_as_the_one_participant_that_hears_the_human(self, monkeypatch):
        edge, rooms = self._edge(monkeypatch)
        task = await self._started(edge)
        try:
            [room] = rooms
            assert room.local_participant.identity == "agent-supervisor"
            assert room.options.auto_subscribe is True
            assert sorted(room.handlers) == ["data_received", "disconnected", "participant_connected", "participant_disconnected", "track_subscribed"]
            assert len(room.local_participant.tracks) == 1
        finally:
            await edge.stop()
            await task

        assert room.disconnects == 1

    @pytest.mark.asyncio
    async def test_the_announced_team_joins_as_participants_of_their_own(self, monkeypatch):
        edge, rooms = self._edge(monkeypatch)
        task = await self._started(edge)
        try:
            await self._announce(edge, self.TEAM)

            assert [room.local_participant.identity for room in rooms] == ["agent-supervisor", "agent-billing", "agent-tech_support"]
            assert [room.options.auto_subscribe for room in rooms] == [True, False, False]
            assert [sorted(room.handlers) for room in rooms] == [
                ["data_received", "disconnected", "participant_connected", "participant_disconnected", "track_subscribed"],
                ["disconnected"],
                ["disconnected"],
            ]
            assert all(len(room.local_participant.tracks) == 1 for room in rooms)
            assert [room.local_participant.attributes for room in rooms] == [{"ak.active": "true"}, {"ak.active": "false"}, {"ak.active": "false"}]
            # Only the agent with the call shows as unmuted.
            assert [participant.track.muted for participant in edge._participants] == [False, True, True]
            assert edge._own_identities == {"agent-supervisor", "agent-billing", "agent-tech_support"}
        finally:
            await edge.stop()
            await task

        assert [room.disconnects for room in rooms] == [1, 1, 1]

    @pytest.mark.asyncio
    async def test_a_reconnect_announcing_the_team_again_joins_no_one_twice(self, monkeypatch):
        edge, rooms = self._edge(monkeypatch)
        task = await self._started(edge)
        try:
            await self._announce(edge, self.TEAM)
            await self._announce(edge, self.TEAM)

            assert len(rooms) == 3
        finally:
            await edge.stop()
            await task

    @pytest.mark.asyncio
    async def test_a_team_announced_while_the_first_participant_joins_waits_for_it(self, monkeypatch):
        """The conversation can announce its team before the edge is in the room; no one joins until it is."""
        edge, rooms = self._edge(monkeypatch)
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
        task = await self._started(edge)
        try:
            assert not edge._connected
            await self._announce(edge, self.TEAM)
            assert len(rooms) == 1 and not edge._joining

            release.set()
            for _ in range(200):
                await asyncio.sleep(0.01)
                if len(rooms) == 3 and not edge._joining:
                    break
            assert [room.local_participant.identity for room in rooms] == ["agent-supervisor", "agent-billing", "agent-tech_support"]
            assert sorted(edge._by_agent) == sorted(self.TEAM)
        finally:
            release.set()
            await edge.stop()
            await task

    @pytest.mark.asyncio
    async def test_a_single_agent_stays_one_participant(self, monkeypatch):
        edge, rooms = self._edge(monkeypatch)
        task = await self._started(edge)
        try:
            await self._announce(edge, ["supervisor"])

            assert len(rooms) == 1
            assert rooms[0].local_participant.attributes == {}
        finally:
            await edge.stop()
            await task

    @pytest.mark.asyncio
    async def test_an_agent_that_cannot_join_speaks_through_the_first(self, monkeypatch, caplog):
        edge, rooms = self._edge(monkeypatch, fail_on=2)
        task = await self._started(edge)
        try:
            with caplog.at_level(logging.WARNING):
                await self._announce(edge, self.TEAM)
                await edge.deliver_chunk(StreamChunk(event=AgentChanged(agent="billing", previous_agent="supervisor")), {})

            assert "agent-billing could not join" in caplog.text
            assert rooms[1].disconnects == 1
            assert sorted(edge._by_agent) == ["supervisor", "tech_support"]
            assert edge._active is edge._participants[0]
            assert "'billing' has no participant of its own" in caplog.text
        finally:
            await edge.stop()
            await task

    @pytest.mark.asyncio
    async def test_without_api_credentials_the_team_speaks_through_one_participant(self, monkeypatch, caplog):
        edge, rooms = self._edge(monkeypatch)
        task = await self._started(edge)
        edge._api_key = edge._api_secret = None  # as with a token minted elsewhere
        try:
            with caplog.at_level(logging.WARNING):
                await self._announce(edge, self.TEAM)

            assert len(rooms) == 1
            assert "needs 'api_key' and 'api_secret'" in caplog.text
        finally:
            await edge.stop()
            await task

    @pytest.mark.asyncio
    async def test_a_listener_that_cannot_join_fails_the_start_and_leaves(self, monkeypatch):
        edge, rooms = self._edge(monkeypatch, fail_on=1)

        with pytest.raises(ConnectionError, match="join refused"):
            await edge.start()

        assert [room.disconnects for room in rooms] == [1]
        assert edge._sender_task is None

    @pytest.mark.asyncio
    async def test_nothing_waits_for_livekit_to_confirm_the_attributes(self, monkeypatch):
        """Regression: LiveKit confirms an attribute update only when the server does; startup used to
        wait on it and, unconfirmed, never finished until the room disconnected."""

        async def unconfirmed(self, attributes):
            await asyncio.Event().wait()

        monkeypatch.setattr(_LocalParticipant, "set_attributes", unconfirmed)
        edge, rooms = self._edge(monkeypatch)
        task = await self._started(edge)
        try:
            await self._announce(edge, self.TEAM)

            assert len(rooms) == 3
            assert len(edge._background_tasks) == 3  # the unconfirmed attribute updates
        finally:
            await edge.stop()
            await task

        await asyncio.sleep(0)
        assert edge._background_tasks == set()

    @pytest.mark.asyncio
    async def test_a_stop_while_an_agent_is_joining_takes_it_out_too(self, monkeypatch):
        edge, rooms = self._edge(monkeypatch, hang_on=2)
        task = await self._started(edge)
        await edge.deliver_chunk(StreamChunk(event=AgentChanged(agent="supervisor", agents=self.TEAM)), {})
        await asyncio.sleep(0.05)

        await edge.stop()
        await task

        assert [room.disconnects for room in rooms] == [1, 1, 1]

    @pytest.mark.asyncio
    async def test_one_room_dropping_ends_the_edge_and_takes_every_participant_out(self, monkeypatch):
        edge, rooms = self._edge(monkeypatch)
        task = await self._started(edge)
        await self._announce(edge, self.TEAM)

        rooms[1].handlers["disconnected"]()
        await asyncio.wait_for(task, timeout=2)

        assert [room.disconnects for room in rooms] == [1, 1, 1]


class TestMultiAgentInbound:
    """Only the human is conversation input: no agent participant's audio or chat ever is."""

    def test_an_agent_participants_audio_is_unsubscribed_and_ignored(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _room_rtc())
        edge = _edge("supervisor", "billing")
        subscribed = []

        edge._on_track_subscribed(
            types.SimpleNamespace(kind="audio"),
            types.SimpleNamespace(set_subscribed=subscribed.append),
            types.SimpleNamespace(identity="agent-billing"),
        )

        assert subscribed == [False]

    @pytest.mark.asyncio
    async def test_the_humans_audio_is_input(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _room_rtc())
        edge = _edge("supervisor", "billing")
        heard = []

        async def listen(track, participant_identity):
            heard.append(("audio", track, participant_identity))

        edge._process_incoming_audio = listen
        track = types.SimpleNamespace(kind="audio")

        edge._on_track_subscribed(track, types.SimpleNamespace(set_subscribed=None), types.SimpleNamespace(identity="caller"))
        await asyncio.sleep(0)

        # The track is listened to as the participant it belongs to (#603).
        assert heard == [("audio", track, "caller")]

    @pytest.mark.asyncio
    async def test_a_participant_joining_opens_the_conversation_whether_or_not_their_mic_is_published(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _room_rtc())
        edge = _edge("supervisor", "billing")
        heard = []

        async def greet(identity):
            heard.append(("greet", identity))

        edge._greet = greet

        edge._on_participant_connected(types.SimpleNamespace(identity="caller"))
        await asyncio.sleep(0)

        assert heard == [("greet", "caller")]

    def test_an_agent_participant_joining_does_not_reopen_the_conversation(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _room_rtc())
        edge = _edge("supervisor", "billing")
        seen = []
        edge._greet = lambda identity: seen.append(identity)

        edge._on_participant_connected(types.SimpleNamespace(identity="agent-billing"))

        assert seen == []

    def test_an_agent_participants_chat_is_ignored(self, monkeypatch):
        edge = _edge("supervisor", "billing")
        seen = []
        monkeypatch.setattr(edge, "_stage_request", lambda request, participant_identity=None: seen.append(request))

        edge._handle_chat_message(
            types.SimpleNamespace(topic="lk-chat", data=b"Billing here.", participant=types.SimpleNamespace(identity="agent-billing"))
        )
        edge._handle_chat_message(_packet("hello"))

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
        edge = _edge("supervisor", "billing", "tech_support")
        edge._loop = asyncio.get_running_loop()
        supervisor, billing, tech_support = edge._participants

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
            await edge.deliver_chunk(chunk, {})
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
        edge = _edge("supervisor", "billing")
        edge._loop = asyncio.get_running_loop()

        await edge.deliver_chunk(self._text("Let me check."), {})
        await edge.deliver_chunk(self._change("billing", "supervisor"), {})

        assert edge._participants[0].room.local_participant.chat == ["Let me check."]
        assert edge._transcript == []

    @pytest.mark.asyncio
    async def test_a_change_does_not_wait_long_for_audio_that_will_not_play_out(self, monkeypatch, caplog):
        monkeypatch.setattr(LiveKitEdgeAdapter, "PLAYOUT_WAIT_SECONDS", 0.05)
        edge = _edge("supervisor", "billing")
        edge._loop = asyncio.get_running_loop()

        async def stuck():
            await asyncio.Event().wait()

        edge._participants[0].audio_source.wait_for_playout = stuck

        with caplog.at_level(logging.WARNING):
            await asyncio.wait_for(edge.deliver_chunk(self._change("billing", "supervisor"), {}), timeout=1)

        assert edge._active is edge._participants[1]
        assert "still playing" in caplog.text

    @pytest.mark.asyncio
    async def test_an_attribute_update_livekit_never_confirms_holds_up_no_audio(self, monkeypatch, caplog):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        monkeypatch.setattr(LiveKitEdgeAdapter, "ATTRIBUTE_TIMEOUT_SECONDS", 0.05)
        edge = _edge("supervisor", "billing")
        edge._loop = asyncio.get_running_loop()

        async def unconfirmed(attributes):
            await asyncio.Event().wait()

        for participant in edge._participants:
            participant.room.local_participant.set_attributes = unconfirmed

        with caplog.at_level(logging.WARNING):
            await asyncio.wait_for(edge.deliver_chunk(self._change("billing", "supervisor"), {}), timeout=1)
            await asyncio.wait_for(edge.deliver_chunk(self._audio(), {}), timeout=1)
            await asyncio.sleep(0.2)

        assert len(edge._participants[1].audio_source.frames) == 1
        assert caplog.text.count("did not confirm") == 2

    @pytest.mark.asyncio
    async def test_an_interrupt_silences_every_agent_participant(self):
        edge = _edge("supervisor", "billing")
        edge._loop = asyncio.get_running_loop()

        await edge.deliver_chunk(StreamChunk(event=Interrupt()), {})
        await asyncio.sleep(0)

        assert [participant.audio_source.clears for participant in edge._participants] == [1, 1]

    @pytest.mark.asyncio
    async def test_a_handoff_to_an_agent_still_joining_is_noted_not_warned(self, caplog):
        """Normal in the first second of a call: no warning is spent on it, so one is left if the join
        then fails."""
        edge = _edge("supervisor", "billing")
        edge._loop = asyncio.get_running_loop()
        del edge._by_agent["billing"]
        edge._joining.add("billing")

        with caplog.at_level(logging.INFO):
            await edge.deliver_chunk(self._change("billing", "supervisor"), {})

        assert "'billing' is still joining the room" in caplog.text
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
        assert edge._warned_agents == set()

    @pytest.mark.asyncio
    async def test_an_agent_without_a_participant_speaks_through_the_first(self, caplog):
        edge = _edge("supervisor", "billing")
        edge._loop = asyncio.get_running_loop()
        await edge.deliver_chunk(self._change("billing", "supervisor"), {})

        with caplog.at_level(logging.WARNING):
            await edge.deliver_chunk(self._change("sales", "billing"), {})
            await edge.deliver_chunk(self._change("billing", "sales"), {})
            await edge.deliver_chunk(self._change("sales", "billing"), {})

        assert edge._active is edge._participants[0]
        assert caplog.text.count("'sales' has no participant of its own") == 1

    @pytest.mark.asyncio
    async def test_an_agent_handed_to_while_joining_moves_to_its_own_participant_once_in(self, monkeypatch):
        """The handoff falls back to the first participant while billing joins; once billing is in,
        its next output goes through its own participant, unmuted, with the first one muted."""
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        edge = _edge("supervisor", "billing")
        edge._loop = asyncio.get_running_loop()
        supervisor, billing = edge._participants
        del edge._by_agent["billing"]  # still joining

        await edge.deliver_chunk(self._change("billing", "supervisor"), {})
        await edge.deliver_chunk(self._audio(), {})
        assert edge._active is supervisor

        edge._by_agent["billing"] = billing  # the join completes
        await edge.deliver_chunk(self._audio(), {})
        await asyncio.sleep(0.05)

        assert edge._active is billing
        assert [len(supervisor.audio_source.frames), len(billing.audio_source.frames)] == [1, 1]
        assert [supervisor.track.muted, billing.track.muted] == [True, False]

    @pytest.mark.asyncio
    async def test_a_single_participant_speaks_for_every_agent(self, monkeypatch):
        monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
        edge = _edge()
        edge._loop = asyncio.get_running_loop()

        await edge.deliver_chunk(self._change("billing", "supervisor"), {})
        await edge.deliver_chunk(self._audio(), {})

        assert edge._active is edge._participants[0]
        assert len(edge._active.audio_source.frames) == 1
        assert edge._active.room.local_participant.attributes == {}
        assert edge._active.track.muted is False


def _audio():
    return StreamChunk(event=AudioDelta(message_id="m", content=base64.b64encode(b"\x00\x00").decode("utf-8")))


def _text(text, message_id="m"):
    return StreamChunk(event=TextDelta(message_id=message_id, content=text))


def _change(agent, previous=None, agents=None):
    return StreamChunk(event=AgentChanged(agent=agent, previous_agent=previous, agents=agents))


def _heard(text, message_id="i1"):
    return StreamChunk(event=InputTranscript(message_id=message_id, content=text))


class TestOpeningPrompt:
    @staticmethod
    def _staged(edge):
        edge._producer = object()
        edge._pending = asyncio.Queue()
        return edge._pending

    @pytest.mark.asyncio
    async def test_the_default_is_the_fixed_hello_word_for_word(self):
        edge = _edge("coordinator")
        pending = self._staged(edge)

        await edge._greet("human-1")

        [staged] = [pending.get_nowait()]
        assert staged.requests[0].prompt == ("A user named human-1 just connected. Say a very short hello to them and confirm you are connected!")

    @pytest.mark.asyncio
    async def test_none_stages_nothing(self):
        edge = _edge("coordinator")
        edge.opening_prompt = lambda identity: None
        pending = self._staged(edge)

        await edge._greet("human-1")

        assert pending.empty()

    @pytest.mark.asyncio
    async def test_a_custom_prompt_is_sent_once_per_subscription(self):
        edge = _edge("coordinator")
        edge.opening_prompt = lambda identity: f"Open the meeting for {identity}."
        pending = self._staged(edge)

        await edge._greet("human-1")

        assert pending.qsize() == 1
        assert pending.get_nowait().requests[0].prompt == "Open the meeting for human-1."

    @pytest.mark.asyncio
    async def test_a_caller_joining_during_start_is_greeted_only_once(self):
        edge = _edge("coordinator")
        pending = self._staged(edge)

        await edge._greet("human-1")  # the participant_connected event
        await edge._greet("human-1")  # the start() snapshot

        assert pending.qsize() == 1

    @pytest.mark.asyncio
    async def test_a_caller_who_rejoins_is_greeted_again(self):
        edge = _edge("coordinator")
        edge._stop_event = asyncio.Event()
        pending = self._staged(edge)

        await edge._greet("human-1")
        edge._on_participant_disconnected(types.SimpleNamespace(identity="human-1"))
        await edge._greet("human-1")

        assert pending.qsize() == 2


@pytest.mark.asyncio
async def test_a_callers_line_is_not_shown_by_the_edge():
    edge = _edge("coordinator")

    await edge.deliver_chunk(_heard("we need booking"), {})

    assert edge._participants[0].room.local_participant.chat == []


class TestTeamBinding:
    def test_an_agent_a_later_change_names_first_is_not_bound_to_the_first_participant(self):
        edge = _edge("coordinator")
        edge._team_lock, edge._pending_team, edge._connected = threading.Lock(), None, False

        edge._show_team("coordinator", ["coordinator"])
        edge._show_team("refunds", ["coordinator", "refunds"])  # a handoff target the starting roster did not hold

        assert edge._by_agent == {"coordinator": edge._participants[0]}


class TestSessionEnd:
    @pytest.mark.asyncio
    async def test_release_sends_one_control_after_the_pending_frames(self):
        edge = _edge("coordinator")
        edge._connected = True
        edge._loop = asyncio.get_running_loop()
        producer = _Producer()
        edge._producer = producer
        edge._pending = asyncio.Queue()
        edge._sender_task = asyncio.create_task(edge._drain_requests())
        edge._stage_request(AgentRequestText(prompt="last words"))
        edge._stage_request(AgentRequestText(prompt="more"))

        await edge._release()
        await edge._release()

        prompts = [[request.prompt for request in call["request"].requests] for call in producer.calls]
        assert prompts == [["last words"], ["more"], []]
        assert [call["request"].end_session for call in producer.calls] == [False, False, True]
        assert producer.calls[-1]["request"].session_id == "s1"

    def test_the_end_control_is_an_empty_request_that_ends_the_session(self):
        edge = _edge("coordinator")

        control = edge._enqueue_end()

        assert control.requests == [] and control.end_session is True
        assert control.session_id == "s1" and control.reply_context == {"session_id": "s1"}
        assert edge._enqueue(AgentRequestText(prompt="hi")).end_session is False

    @pytest.mark.asyncio
    async def test_frames_after_the_end_are_not_staged(self):
        edge = _edge("coordinator")
        edge._connected = True
        edge._producer = _Producer()
        edge._pending = asyncio.Queue()
        edge._sender_task = asyncio.create_task(edge._drain_requests())

        await edge._release()
        edge._stage_request(AgentRequestText(prompt="late"))

        assert edge._pending.empty()

    @pytest.mark.asyncio
    async def test_a_edge_that_never_connected_sends_no_control(self):
        edge = _edge("coordinator")
        edge._producer = _Producer()

        await edge._release()

        assert edge._producer.calls == []

    @pytest.mark.asyncio
    async def test_a_failing_control_is_logged_and_release_still_leaves_the_room(self, caplog):
        edge = _edge("coordinator")
        edge._connected = True

        class _Broken:
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("broker down")

        edge._producer = _Broken()
        participant = edge._participants[0]
        room = participant.room
        with caplog.at_level(logging.WARNING, logger="ak.integration.livekit"):
            await edge._release()

        assert "broker down" in caplog.text
        assert room.disconnects == 1

    @pytest.mark.asyncio
    async def test_a_broker_that_does_not_answer_cannot_hold_up_release(self, monkeypatch, caplog):
        monkeypatch.setattr(LiveKitEdgeAdapter, "SESSION_END_TIMEOUT_SECONDS", 0.1)
        edge = _edge("coordinator")
        edge._connected = True
        release = threading.Event()

        class _Stuck:
            def enqueue(self, *args, **kwargs):
                release.wait(5)

        edge._producer = _Stuck()
        room = edge._participants[0].room
        try:
            with caplog.at_level(logging.WARNING, logger="ak.integration.livekit"):
                await asyncio.wait_for(edge._release(), 2)
        finally:
            release.set()

        assert "was not accepted within" in caplog.text
        assert room.disconnects == 1

    @pytest.mark.asyncio
    async def test_the_control_is_not_sent_when_staged_input_is_still_unsent(self, monkeypatch, caplog):
        """Sent anyway it would pass the staged frames: the pool would end the session and drop them as late input."""
        monkeypatch.setattr(LiveKitEdgeAdapter, "SESSION_END_TIMEOUT_SECONDS", 0.1)
        edge = _edge("coordinator")
        edge._connected = True
        edge._loop = asyncio.get_running_loop()
        edge._pending = asyncio.Queue()
        release = threading.Event()

        class _Slow(_Producer):
            def enqueue(self, adapter_name, request, source=None):
                release.wait(5)
                super().enqueue(adapter_name, request, source)

        producer = _Slow()
        edge._producer = producer
        edge._sender_task = asyncio.create_task(edge._drain_requests())
        edge._stage_request(AgentRequestText(prompt="still on its way"))
        await asyncio.sleep(0.02)  # the sender has taken it and is waiting on the broker
        try:
            with caplog.at_level(logging.WARNING, logger="ak.integration.livekit"):
                await asyncio.wait_for(edge._release(), 2)
        finally:
            release.set()
            await asyncio.sleep(0.05)

        assert "not sending the end-of-session control" in caplog.text
        assert [call["request"].end_session for call in producer.calls] == [False]  # the staged frame only, no control

    @pytest.mark.asyncio
    async def test_start_greets_a_caller_already_in_the_room(self, monkeypatch):
        """LiveKit raises participant_connected only for later joins; a caller who was there first is greeted from start()."""
        _config(monkeypatch)
        edge = LiveKitEdgeAdapter(session_id="room-r")

        class _Room2(_Room):
            async def connect(self, url, token, options):
                self.options = options
                self.remote_participants = {
                    "PA_caller": types.SimpleNamespace(identity="caller-1"),
                    "PA_self": types.SimpleNamespace(identity=next(iter(edge._own_identities), "none")),
                }

        class _RtcStub:
            RoomOptions = staticmethod(lambda **kwargs: kwargs)
            TrackSource = types.SimpleNamespace(SOURCE_MICROPHONE=2)
            TrackPublishOptions = staticmethod(lambda **kwargs: kwargs)
            AudioSource = staticmethod(lambda **kwargs: _AudioSource())
            LocalAudioTrack = types.SimpleNamespace(create_audio_track=staticmethod(lambda name, source: _Track(name)))
            Room = _Room2

        monkeypatch.setattr(livekit_adapter, "rtc", _RtcStub)
        producer = _Producer()
        monkeypatch.setattr(edge, "_init_producer", lambda: setattr(edge, "_producer", producer))
        task = asyncio.create_task(edge.start())
        try:
            for _ in range(200):
                if producer.calls:
                    break
                await asyncio.sleep(0.01)
        finally:
            await edge.stop()
            await asyncio.wait_for(task, 5)

        prompts = [request.prompt for call in producer.calls for request in call["request"].requests]
        assert prompts and "caller-1" in prompts[0]
        assert not any("agent-" in prompt for prompt in prompts)

    @pytest.mark.asyncio
    async def test_start_marks_the_edge_ready_once_connected(self, monkeypatch):
        _config(monkeypatch)
        edge = LiveKitEdgeAdapter(session_id="room-r")

        class _Room2(_Room):
            async def connect(self, url, token, options):
                self.options = options
                self.remote_participants = {"PA_caller": types.SimpleNamespace(identity="caller-1")}

        class _RtcStub:
            RoomOptions = staticmethod(lambda **kwargs: kwargs)
            TrackSource = types.SimpleNamespace(SOURCE_MICROPHONE=2)
            TrackPublishOptions = staticmethod(lambda **kwargs: kwargs)
            AudioSource = staticmethod(lambda **kwargs: _AudioSource())
            LocalAudioTrack = types.SimpleNamespace(create_audio_track=staticmethod(lambda name, source: _Track(name)))
            Room = _Room2

        monkeypatch.setattr(livekit_adapter, "rtc", _RtcStub)
        monkeypatch.setattr(edge, "_init_producer", lambda: setattr(edge, "_producer", _Producer()))
        task = asyncio.create_task(edge.start())
        for _ in range(100):
            if edge._connected:
                break
            await asyncio.sleep(0.01)

        assert edge._connected
        await edge.stop()
        await asyncio.wait_for(task, 5)

    @pytest.mark.asyncio
    async def test_start_ends_the_edge_when_no_caller_is_in_the_room(self, monkeypatch):
        _config(monkeypatch)
        edge = LiveKitEdgeAdapter(session_id="room-r")
        rooms = []

        class _Room2(_Room):
            async def connect(self, url, token, options):
                self.options = options
                self.remote_participants = {}
                rooms.append(self)

        class _RtcStub:
            RoomOptions = staticmethod(lambda **kwargs: kwargs)
            TrackSource = types.SimpleNamespace(SOURCE_MICROPHONE=2)
            TrackPublishOptions = staticmethod(lambda **kwargs: kwargs)
            AudioSource = staticmethod(lambda **kwargs: _AudioSource())
            LocalAudioTrack = types.SimpleNamespace(create_audio_track=staticmethod(lambda name, source: _Track(name)))
            Room = _Room2

        monkeypatch.setattr(livekit_adapter, "rtc", _RtcStub)
        monkeypatch.setattr(edge, "_init_producer", lambda: setattr(edge, "_producer", _Producer()))

        await asyncio.wait_for(edge.start(), 2)

        assert edge._stop_event.is_set()
        assert rooms[0].disconnects == 1


class TestCallersLeaving:
    """The last caller leaving ends the edge, through LiveKit's participant_disconnected."""

    @staticmethod
    def _left(edge, still_here):
        edge._stop_event = asyncio.Event()
        edge._participants[0].room.remote_participants = {identity: SimpleNamespace(identity=identity) for identity in still_here}
        edge._on_participant_disconnected(SimpleNamespace(identity="caller-1"))
        return edge._stop_event.is_set()

    def test_the_last_caller_leaving_stops_the_edge(self):
        assert self._left(_edge(), still_here=[]) is True

    def test_an_edge_is_ending_once_its_last_caller_left(self):
        """The host holds a caller's rejoin while the edge is ending and starts a new edge after it."""
        edge = _edge()
        assert not edge.ending  # not started
        self._left(edge, still_here=["caller-2"])
        assert not edge.ending
        self._left(edge, still_here=[])
        assert edge.ending

    def test_a_caller_still_in_the_room_keeps_it_going(self):
        assert self._left(_edge(), still_here=["caller-2"]) is False

    def test_the_edges_own_agents_do_not_count_as_callers(self):
        assert self._left(_edge(), still_here=["agent-general"]) is True
