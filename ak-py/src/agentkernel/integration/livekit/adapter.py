import asyncio
import base64
import json
import logging
import uuid
from typing import Dict, Optional

from livekit import api, rtc

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequestText, StreamChunk
from ...core.realtime import EDGE_SAMPLE_RATE
from ..adapter.base import StatefulEdgeAdapter

_log = logging.getLogger("ak.integration.livekit")

INTEGRATION_NAME = "livekit"
# Cap on inbound requests staged for the sender task (~6 s of audio). A reachable broker drains
# far faster than the edge produces, so this only bites when the broker is slow or down, where
# dropping the oldest frame beats growing the queue without bound.
_MAX_PENDING_REQUESTS = 64


class LiveKitEdgeGateway(StatefulEdgeAdapter):
    """Bridges a LiveKit WebRTC room with the Agent Kernel queue.

    Unlike standard messaging webhook adapters which are stateless and split into Inbound/Outbound
    halves, WebRTC requires a stateful, persistent connection to a room. This gateway owns that
    connection: it pushes user audio and chat text to the input queue, and — as the ``livekit``
    outbound adapter — plays the agent's streamed audio and transcript back to the room. It is
    hosted by ``GatewayRunner``, which registers it as the ``livekit`` outbound adapter on start.

    Every agent of the conversation is shown as a participant of its own, with nothing to
    configure. The gateway joins the room as one agent participant, the one that hears the human;
    when the conversation starts, its first ``AgentChanged`` names the whole team (every agent the
    starting one can hand off to), and every other agent joins as a participant with its own
    connection and audio track. Later ``AgentChanged`` events decide which of them is heard: the
    others stay connected with their track muted, so a room client shows only the agent with the
    call as unmuted. No agent participant's audio or chat is ever taken as input.
    A single agent, with no handoffs, is one participant, as before.
    """

    name = INTEGRATION_NAME
    # Set on every agent participant: "true" on the one speaking, so a client UI can show who has the call.
    ACTIVE_ATTRIBUTE = "ak.active"
    # On a change of speaker, how long the previous agent's queued audio may play out before the next
    # agent is heard. Bounds how long a change can hold up the chunks behind it, an interrupt among them.
    PLAYOUT_WAIT_SECONDS: float = 2.0
    # How long LiveKit may take to confirm an ACTIVE_ATTRIBUTE update; nothing waits on it but a warning.
    ATTRIBUTE_TIMEOUT_SECONDS: float = 5.0

    class _AgentParticipant:
        """One agent participant in the room: its own connection, identity and published audio track."""

        def __init__(self, agent: Optional[str], identity: Optional[str], token: str):
            """
            :param agent: The agent it speaks for, or None for a single participant that speaks for every agent.
            :param identity: Its identity in the room, when this gateway minted its token.
            :param token: The access token it joins with.
            """
            self.agent = agent
            self.identity = identity
            self.token = token
            self.room: Optional["rtc.Room"] = None
            self.audio_source: Optional["rtc.AudioSource"] = None
            self.track: Optional["rtc.LocalAudioTrack"] = None

        async def join(self, room: "rtc.Room", url: str, listen: bool, muted: bool = False) -> None:
            """Connect ``room`` and publish this agent's audio track.

            :param room: The room, with its event handlers already registered.
            :param url: The LiveKit server URL.
            :param listen: Subscribe to the room's tracks; only the participant that hears the human does.
            :param muted: Publish the track muted: the agent is not the one heard.
            """
            self.room = room
            await room.connect(url, self.token, options=rtc.RoomOptions(auto_subscribe=listen))
            source = rtc.AudioSource(sample_rate=EDGE_SAMPLE_RATE, num_channels=1)
            track = rtc.LocalAudioTrack.create_audio_track("ai-voice", source)
            options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            try:
                await asyncio.wait_for(room.local_participant.publish_track(track, options), timeout=10.0)
            except asyncio.TimeoutError as e:
                raise RuntimeError(f"Timed out publishing the audio track of {self.identity or 'the agent'}") from e
            except Exception as e:
                raise RuntimeError(f"Failed to publish the audio track of {self.identity or 'the agent'}: {e}") from e
            if muted:
                track.mute()
            self.audio_source = source
            self.track = track

        async def leave(self) -> None:
            """Disconnect from the room; safe to call more than once, and after a join that failed."""
            room, self.room, self.audio_source, self.track = self.room, None, None, None
            if room is not None:
                await room.disconnect()

    def __init__(
        self,
        room_url: Optional[str] = None,
        agent_name: Optional[str] = None,
        session_id: Optional[str] = None,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        super().__init__()
        config = AKConfig.get()
        self.room_url = room_url or config.livekit.url
        # Carried on every request so the runner binds this room's session to the configured agent;
        # None (nothing configured) leaves selection to the runner's default agent.
        self.agent = agent_name or config.livekit.agent or None
        self.session_id = session_id or str(uuid.uuid4())
        # Mic audio is accumulated to one input-queue message of this many bytes; 0 passes every
        # frame LiveKit hands us straight through (lowest latency, many more queue messages).
        self._input_batch_ms = config.execution.realtime.input_batch_ms
        self._input_batch_bytes = int(EDGE_SAMPLE_RATE * 2 * (self._input_batch_ms / 1000))

        # Kept to give each agent of the team a token of its own when the conversation announces it.
        self._api_key = api_key or config.livekit.api_key
        self._api_secret = api_secret or config.livekit.api_secret
        # The participant that hears the human; it speaks for the starting agent.
        self._participants = [self._single_participant(token)]
        # Each agent's participant, once it is in the room.
        self._by_agent: dict[str, LiveKitEdgeGateway._AgentParticipant] = {}
        # Known before a participant joins, so a track it publishes is never taken for the human's.
        self._own_identities = {participant.identity for participant in self._participants if participant.identity}
        # Heard until an AgentChanged names another agent.
        self._active = self._participants[0]
        self.token = self._active.token
        # Agents of the team whose participant is joining now.
        self._joining: set[str] = set()
        # Agents already warned about, once each: they have no participant of their own.
        self._warned_agents: set[str] = set()
        # Work running on the gateway's loop (team joins, ACTIVE_ATTRIBUTE updates), cancelled on release.
        self._background_tasks: set[asyncio.Task] = set()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False
        # Bounded staging queue drained by one sender task, so inbound frames never spawn an
        # unbounded task per frame: a slow or unreachable broker applies backpressure here.
        self._pending: Optional["asyncio.Queue"] = None
        self._sender_task: Optional[asyncio.Task] = None
        # Accumulated from TextDelta chunks; published as one chat message when the turn ends.
        self._transcript: list[str] = []
        self._interrupted = False

    def _single_participant(self, token: Optional[str]) -> _AgentParticipant:
        if token:
            return self._AgentParticipant(self.agent, None, token)
        if not (self._api_key and self._api_secret):
            raise ValueError("Either 'token' or both 'api_key' and 'api_secret' must be provided in code or config")
        # The name the agent appears under in the room; cosmetic, unlike ``self.agent``.
        name = self.agent or "general"
        return self._AgentParticipant(self.agent, f"agent-{name}", self._mint_token(name))

    def _mint_token(self, name: str) -> str:
        # can_update_own_metadata lets the participant set its ACTIVE_ATTRIBUTE.
        grants = api.VideoGrants(room_join=True, room=self.session_id, can_update_own_metadata=True)
        return api.AccessToken(self._api_key, self._api_secret).with_identity(f"agent-{name}").with_name(f"{name} Agent").with_grants(grants).to_jwt()

    async def start(self) -> None:
        """Join the room as the participant that hears the human, and bridge audio until the pipeline shuts down.

        The rest of the conversation's team joins when the conversation announces it
        (:meth:`_show_team`). If joining fails, the participant leaves before the error is raised:
        ``GatewayRunner`` does not call :meth:`stop` for a start that failed.
        """
        _log.info(f"Connecting to LiveKit room at {self.room_url}")

        self._stop_event = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self._init_producer()
        self._pending = asyncio.Queue(maxsize=_MAX_PENDING_REQUESTS)
        self._sender_task = asyncio.create_task(self._drain_requests())

        try:
            for index, participant in enumerate(self._participants):
                listen = index == 0
                await participant.join(self._new_room(listen), self.room_url, listen)
        except Exception:
            await self._release()
            raise
        self._connected = True
        _log.info("LiveKit WebRTC connection established; AI audio published.")
        self._show_speaking()

        await self._stop_event.wait()
        # One participant's room dropping ends the gateway; the others must not stay behind in the room.
        await self._release()

    def _new_room(self, listen: bool) -> "rtc.Room":
        """A room for one participant, with its handlers registered before it connects.

        :param listen: The participant hears the human, so it handles the room's tracks and chat.
        """
        room = rtc.Room()
        room.on("disconnected", self._on_disconnected)
        if listen:
            room.on("track_subscribed", self._on_track_subscribed)
            room.on("data_received", self._handle_chat_message)
        return room

    def _on_disconnected(self, *args, **kwargs) -> None:
        _log.info(f"LiveKit room {self.room_url} disconnected.")
        if not self._stop_event.is_set():
            self._stop_event.set()

    async def stop(self) -> None:
        """Gracefully disconnect and release resources."""
        _log.info("LiveKitEdgeGateway shutting down: disconnecting from room")
        await self._release()
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        _log.info("LiveKitEdgeGateway disconnected successfully")

    async def _release(self) -> None:
        """Stop the sender task and the background work, and take every agent participant out of the room."""
        if self._sender_task:
            self._sender_task.cancel()
            self._sender_task = None
        for task in list(self._background_tasks):
            task.cancel()
        for participant in self._participants:
            try:
                await participant.leave()
            except Exception:
                _log.exception(f"Failed to disconnect agent participant {participant.identity or participant.agent}")

    # -- inbound: room -> queue --------------------------------------------------------------

    def _on_track_subscribed(self, track: "rtc.Track", publication: "rtc.RemoteTrackPublication", participant: "rtc.RemoteParticipant") -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if participant.identity in self._own_identities:
            # Another agent participant of this gateway: AI speech is never conversation input.
            publication.set_subscribed(False)
            return
        _log.info(f"Subscribed to audio track from {participant.identity}")
        asyncio.create_task(self._greet(participant.identity))
        asyncio.create_task(self._process_incoming_audio(track))

    async def _greet(self, participant_identity: str) -> None:
        """Kick off the conversation once a participant's mic appears."""
        _log.info(f"Triggering auto-greeting for {participant_identity}")
        prompt = f"A user named {participant_identity} just connected their microphone. Say a very short hello to them and confirm you are connected!"
        self._stage_request(AgentRequestText(prompt=prompt))

    def _handle_chat_message(self, data_packet: "rtc.DataPacket") -> None:
        if data_packet.topic not in ("chat", "lk-chat-topic", "lk-chat", ""):
            return
        if getattr(data_packet.participant, "identity", None) in self._own_identities:
            # An agent participant's published transcript, not something the human typed.
            return
        try:
            payload_str = data_packet.data.decode("utf-8")
            try:
                payload = json.loads(payload_str)
                text = payload.get("message", payload_str)
            except json.JSONDecodeError:
                text = payload_str
            if not text:
                return
            _log.info(f"Text chat received from {data_packet.participant.identity}: {text}")
            self._stage_request(AgentRequestText(prompt=text))
        except Exception as e:
            _log.error(f"Failed to process chat: {e}")

    async def _process_incoming_audio(self, track: "rtc.Track") -> None:
        """Pass continuous mic audio to the queue, batched per ``execution.realtime.input_batch_ms``.

        Batching keeps the input-queue message count (and broker cost/overhead) low; setting the
        batch to 0 passes every incoming frame straight through.
        """
        audio_stream = rtc.AudioStream(track, sample_rate=EDGE_SAMPLE_RATE, num_channels=1)
        _log.info(f"Listening for audio stream (batching at {self._input_batch_ms} ms; 0 = pass-through)...")

        buffer = bytearray()

        async for event in audio_stream:
            try:
                raw_bytes = event.frame.data.tobytes()
                if not raw_bytes:
                    continue
                if self._input_batch_bytes == 0:
                    self._stage_request(self._enqueue_audio(raw_bytes))
                    continue
                buffer.extend(raw_bytes)
                if len(buffer) >= self._input_batch_bytes:
                    self._stage_request(self._enqueue_audio(buffer))
                    buffer.clear()
            except Exception as e:
                _log.error(f"Failed to process incoming audio frame: {e}")

        if buffer:
            self._stage_request(self._enqueue_audio(buffer))

    def _stage_request(self, request) -> None:
        """Stage one request for the sender task, tagged for this livekit session.

        Staging (rather than spawning a fire-and-forget task per frame) bounds what a stalled
        broker can accumulate; a full queue drops the frame with a warning instead of growing.
        """
        if self._producer is None or self._pending is None:
            return

        try:
            self._pending.put_nowait(self._enqueue(request))
        except asyncio.QueueFull:
            _log.warning(f"Realtime input queue is full for session {self.session_id}; dropping a frame (broker slow or unreachable?)")

    async def _drain_requests(self) -> None:
        """Send staged inbound requests to the input queue, one at a time, off the room loop.

        ``producer.enqueue`` is synchronous and talks to the broker, so it runs in a worker thread
        to keep the room's event loop responsive; doing it serially keeps the broker hop ordered.
        """
        assert self._pending is not None
        while True:
            inbound = await self._pending.get()
            try:
                await asyncio.to_thread(self._producer.enqueue, self.name, inbound)
            except Exception as e:
                _log.error(f"Failed to enqueue request for session {self.session_id}: {e}")

    # -- outbound: queue -> room -------------------------------------------------------------

    async def deliver_chunk(self, chunk: StreamChunk, reply_context: Dict[str, str]) -> None:
        """Play one streamed ``StreamChunk`` back to the room, through the agent participant speaking.

        Audio deltas play immediately; transcript deltas are accumulated and published as one
        chat message when the turn's ``done`` chunk arrives; a barge-in ``Interrupt`` clears
        playback and drops the partial transcript; an ``AgentChanged`` hands the voice to that
        agent's participant; an error chunk is surfaced to the room so it is never left silent.
        """
        if chunk.error:
            # A model/turn failure arrives as a terminal error chunk. Drop any half-accumulated
            # transcript so a stale sentence is not published, then tell the user.
            self._transcript.clear()
            self._interrupted = False
            self._clear_playback()
            await self.deliver_error(chunk.error, reply_context)
            return

        event = chunk.event
        if event is not None:
            if event.type == "audio_delta":
                audio_bytes = base64.b64decode(event.content)
                source = self._active.audio_source
                if audio_bytes and source is not None:
                    frame = rtc.AudioFrame(
                        data=audio_bytes,
                        sample_rate=EDGE_SAMPLE_RATE,
                        num_channels=1,
                        samples_per_channel=len(audio_bytes) // 2,
                    )
                    await self._run_on_room(source.capture_frame(frame))
            elif event.type == "text_delta":
                self._transcript.append(event.content)
            elif event.type == "interrupt":
                # Barge-in: stop buffered AI audio and don't publish a half-said sentence.
                _log.info("Barge-in detected: clearing buffered AI audio")
                self._interrupted = True
                self._clear_playback()
            elif event.type == "agent_changed":
                if event.agents:
                    self._show_team(event.agent, event.agents)
                await self._change_speaker(event.agent)

        if chunk.done:
            transcript = "".join(self._transcript).strip()
            self._transcript.clear()
            if self._interrupted:
                self._interrupted = False
                self._clear_playback()
            elif transcript:
                _log.info(f"AI response: {transcript}")
                await self._publish_text(transcript)

    async def _change_speaker(self, agent: str) -> None:
        """Make the participant of ``agent`` the one heard.

        A single participant speaks for every agent, so nothing changes. Otherwise the previous
        agent's words are published as its own, its queued audio plays out (bounded, so the change
        cannot hold up an interrupt behind it for long) and its track is muted, and the new agent's
        track is unmuted: it is heard, and shown as speaking, from here on.
        An agent without a participant of its own in the room (still joining, or unable to join)
        speaks through the first one, with a warning, rather than going unheard.
        """
        if len(self._participants) == 1:
            return
        speaker = self._by_agent.get(agent)
        if speaker is None:
            if agent not in self._warned_agents:
                self._warned_agents.add(agent)
                _log.warning(f"Agent '{agent}' has no participant of its own in the room; it speaks through '{self._participants[0].agent}'")
            speaker = self._participants[0]
        previous = self._active
        if speaker is previous:
            return

        transcript = "".join(self._transcript).strip()
        self._transcript.clear()
        if transcript and not self._interrupted:
            await self._publish_text(transcript, previous)
        if previous.audio_source is not None:
            try:
                await asyncio.wait_for(self._run_on_room(previous.audio_source.wait_for_playout()), timeout=self.PLAYOUT_WAIT_SECONDS)
            except asyncio.TimeoutError:
                _log.warning(f"Agent '{previous.agent}' was still playing after {self.PLAYOUT_WAIT_SECONDS}s; '{speaker.agent}' speaks now")

        _log.info(f"Agent participant speaking: '{previous.agent}' -> '{speaker.agent}'")
        self._set_muted(previous, True)
        self._set_muted(speaker, False)
        self._active = speaker
        self._show_speaking()

    def _set_muted(self, participant: _AgentParticipant, muted: bool) -> None:
        """Mute or unmute the participant's track on the gateway's loop, which owns it.

        Queued ahead of the audio that follows, so the new speaker is unmuted before its first frame.
        """
        if participant.track is None or self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._apply_mute, participant, muted)
        except RuntimeError:
            pass  # the gateway's loop has closed

    @staticmethod
    def _apply_mute(participant: _AgentParticipant, muted: bool) -> None:
        track = participant.track
        if track is None:
            return
        try:
            track.mute() if muted else track.unmute()
        except Exception as e:
            _log.warning(f"Could not {'mute' if muted else 'unmute'} agent participant {participant.identity}: {e}")

    def _show_team(self, starting: str, agents: list[str]) -> None:
        """Give every agent of the conversation's team a participant of its own.

        The starting agent speaks through the participant that is already in the room; every other
        agent joins in the background, so the voice never waits on a join, and is heard through its
        own participant once it is in. Announced again after a reconnect, when only the agents not
        in the room yet join. Each agent needs a token of its own, so without ``api_key`` and
        ``api_secret`` the team speaks through the one participant, with a warning.

        :param starting: The agent the conversation starts with.
        :param agents: Every agent the conversation can hand off to, the starting one first.
        """
        self._by_agent.setdefault(starting, self._participants[0])
        missing = [name for name in agents if name not in self._by_agent and name not in self._joining]
        if not missing or self._loop is None:
            return
        if not (self._api_key and self._api_secret):
            if starting not in self._warned_agents:
                self._warned_agents.add(starting)
                _log.warning(f"Showing {missing} as participants of their own needs 'api_key' and 'api_secret'; they speak through '{starting}'")
            return
        self._joining.update(missing)
        try:
            self._loop.call_soon_threadsafe(self._join_team, missing)
        except RuntimeError:
            pass  # the gateway's loop has closed

    def _join_team(self, names: list[str]) -> None:
        # The participant heard so far now has others beside it: mark it as the one speaking. Each
        # joining participant marks itself once it is in.
        self._in_background(self._update_attribute(self._active))
        for name in names:
            participant = self._AgentParticipant(name, f"agent-{name}", self._mint_token(name))
            self._own_identities.add(participant.identity)
            # Listed before it joins, so a release while it is joining takes it out too.
            self._participants.append(participant)
            self._in_background(self._join(participant))

    async def _join(self, participant: _AgentParticipant) -> None:
        try:
            await participant.join(self._new_room(listen=False), self.room_url, listen=False, muted=True)
        except Exception:
            _log.exception(f"Agent participant {participant.identity} could not join; '{participant.agent}' speaks through the first participant")
            self._participants.remove(participant)
            self._joining.discard(participant.agent)
            await participant.leave()
            return
        self._by_agent[participant.agent] = participant
        self._joining.discard(participant.agent)
        _log.info(f"Agent '{participant.agent}' joined the room as {participant.identity}")
        self._in_background(self._update_attribute(participant))

    def _in_background(self, coro) -> None:
        """Run ``coro`` on the gateway's loop (the caller is on it), kept until done and cancelled on release."""
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _show_speaking(self) -> None:
        """Mark on every agent participant whether it is the one heard, without waiting for LiveKit.

        LiveKit completes an attribute update only once the server confirms it, which can take long
        or never come, so the updates run in the background on the gateway's loop, each bounded and a
        failure logged: neither startup nor the voice ever waits on them. Each update reads who is
        heard when it starts, not when it was asked for.
        """
        if self._loop is None or len(self._participants) == 1:
            return
        try:
            self._loop.call_soon_threadsafe(self._start_attribute_updates)
        except RuntimeError:
            pass  # the gateway's loop has closed

    def _start_attribute_updates(self) -> None:
        for participant in self._participants:
            if participant.audio_source is not None:  # in the room, not still joining
                self._in_background(self._update_attribute(participant))

    async def _update_attribute(self, participant: _AgentParticipant) -> None:
        room = participant.room
        if room is None:
            return
        value = "true" if participant is self._active else "false"
        try:
            await asyncio.wait_for(room.local_participant.set_attributes({self.ACTIVE_ATTRIBUTE: value}), timeout=self.ATTRIBUTE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            _log.warning(
                f"LiveKit did not confirm {self.ACTIVE_ATTRIBUTE}={value} on {participant.identity} within {self.ATTRIBUTE_TIMEOUT_SECONDS}s"
            )
        except Exception as e:
            _log.warning(f"Could not set {self.ACTIVE_ATTRIBUTE} on agent participant {participant.identity}: {e}")

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        """Publish a completed reply as chat text (used for the non-streamed fallback path)."""
        text = getattr(reply, "response", "") or str(reply)
        if text:
            await self._publish_text(text)

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        """Surface a failure to the room so the user is never left silent."""
        await self._publish_text(message)

    async def _publish_text(self, text: str, participant: Optional[_AgentParticipant] = None) -> None:
        """Publish ``text`` as a chat message from ``participant``, by default the one speaking."""
        room = (participant or self._active).room
        if room is None:
            return
        payload = json.dumps({"id": str(uuid.uuid4()), "message": text, "timestamp": 0})
        await self._run_on_room(room.local_participant.publish_data(payload.encode("utf-8"), reliable=True, topic="lk-chat"))

    def _clear_playback(self) -> None:
        """Drop AI audio still queued on every agent participant's source so a barge-in cuts it off.

        Called from the Response Handler thread; ``clear_queue`` is synchronous and must run on
        the gateway's own loop, so it is marshalled across with ``call_soon_threadsafe``.
        """
        if self._loop is None:
            return
        for participant in self._participants:
            if participant.audio_source is None:
                continue
            try:
                self._loop.call_soon_threadsafe(participant.audio_source.clear_queue)
            except RuntimeError:
                pass

    async def _run_on_room(self, coro) -> None:
        """Await a room coroutine on the gateway's own loop.

        Deliveries arrive on the Response Handler's thread (its own short-lived loop), but the
        room and audio source are bound to the gateway's loop, so the call is marshalled across.
        """
        if self._loop is None:
            coro.close()
            return
        if self._loop is asyncio.get_running_loop():
            await coro
            return
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        await asyncio.wrap_future(future)
