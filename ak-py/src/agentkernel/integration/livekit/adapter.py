import asyncio
import base64
import json
import logging
import threading
import uuid
from typing import Any

from livekit import api, rtc

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequestText, AgentRequestVoice, StreamChunk
from ...core.realtime import EDGE_SAMPLE_RATE
from ..adapter.base import EdgeLifecycleAdapter, EdgeLifecycleEvent, StatefulEdgeAdapter

_log = logging.getLogger("ak.integration.livekit")

INTEGRATION_NAME = "livekit"
# Cap on inbound requests staged for the sender task (~6 s of audio); only reached when the broker is slow or down.
_MAX_PENDING_REQUESTS = 64


class LiveKitEdgeAdapter(StatefulEdgeAdapter):
    """Bridges a LiveKit WebRTC room with the Agent Kernel queue; ``LiveKitLifecycleAdapter`` builds one per room.

    Pushes the caller's audio and chat text to the input queue and plays the agent's streamed audio
    and transcript back to the room. Each agent of the team joins as its own participant; the one
    speaking is unmuted, the rest stay muted. Override :meth:`opening_prompt` to change how a call opens.
    """

    name = INTEGRATION_NAME
    # Set on every agent participant: "true" on the one speaking, so a client UI can show who has the call.
    ACTIVE_ATTRIBUTE = "ak.active"
    # On a change of speaker, how long the previous agent's queued audio may play out before the next agent is heard.
    PLAYOUT_WAIT_SECONDS: float = 2.0
    # How long LiveKit may take to confirm an ACTIVE_ATTRIBUTE update before a warning.
    ATTRIBUTE_TIMEOUT_SECONDS: float = 5.0
    # How long a stopping edge waits for staged frames to reach the queue before the end-of-session control.
    SESSION_END_TIMEOUT_SECONDS: float = 2.0

    class _AgentParticipant:
        """One agent participant in the room: its own connection, identity and published audio track."""

        def __init__(self, agent: str | None, identity: str | None, token: str):
            """
            :param agent: The agent it speaks for, or None for a single participant that speaks for every agent.
            :param identity: Its identity in the room, when this edge minted its token.
            :param token: The access token it joins with.
            """
            self.agent = agent
            self.identity = identity
            self.token = token
            self.room: "rtc.Room | None" = None
            self.audio_source: "rtc.AudioSource | None" = None
            self.track: "rtc.LocalAudioTrack | None" = None

        async def join(self, room: "rtc.Room", url: str, listen: bool, muted: bool = False) -> None:
            """Connect ``room`` and publish this agent's audio track.

            :param room: The room, with its event handlers already registered.
            :param url: The LiveKit server URL.
            :param listen: Subscribe to the room's tracks; only the participant that hears the caller does.
            :param muted: Publish the track muted.
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
        session_id: str,
        room_url: str | None = None,
        agent_name: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        super().__init__()
        config = AKConfig.get()
        self.room_url = room_url or config.livekit.url
        # None leaves agent selection to the runner's default agent.
        self.agent = agent_name or config.livekit.agent or None
        self.session_id = session_id
        # Mic audio per input-queue message; 0 sends every frame as it arrives.
        self._input_batch_ms = config.execution.realtime.input_batch_ms
        self._input_batch_bytes = int(EDGE_SAMPLE_RATE * 2 * (self._input_batch_ms / 1000))

        self._api_key = api_key or config.livekit.api_key
        self._api_secret = api_secret or config.livekit.api_secret
        # The first participant hears the caller and speaks for the starting agent.
        self._participants = [self._single_participant()]
        self._by_agent: dict[str, LiveKitEdgeAdapter._AgentParticipant] = {}
        # Known before a participant joins, so its track is never taken for the caller's.
        self._own_identities = {participant.identity for participant in self._participants if participant.identity}
        self._active = self._participants[0]
        self.token = self._active.token
        self._joining: set[str] = set()
        self._warned_agents: set[str] = set()
        # Callers already greeted, so a join racing the start snapshot is greeted only once.
        self._greeted: set[str] = set()
        # May differ from self._active while its participant is still joining.
        self._speaking_agent: str | None = None
        self._background_tasks: set[asyncio.Task] = set()

        self._loop: asyncio.AbstractEventLoop | None = None
        # Created by start(), on the edge's own event loop.
        self._stop_event: asyncio.Event | None = None
        self._connected = False
        # The team announcement arrives on the Response Handler thread, while start() may still be joining.
        self._team_lock = threading.Lock()
        self._pending_team: tuple[str, list[str]] | None = None
        self._pending: "asyncio.Queue | None" = None
        self._sender_task: asyncio.Task | None = None
        self._transcript: list[str] = []
        self._interrupted = False
        self._ending = False
        self._end_sent = False

    def _single_participant(self) -> _AgentParticipant:
        if not (self._api_key and self._api_secret):
            raise ValueError("Both 'api_key' and 'api_secret' must be provided in code or config")
        name = self.agent or "general"
        return self._AgentParticipant(self.agent, f"agent-{name}", self._mint_token(name))

    def _mint_token(self, name: str) -> str:
        # can_update_own_metadata lets the participant set its ACTIVE_ATTRIBUTE.
        grants = api.VideoGrants(room_join=True, room=self.session_id, can_update_own_metadata=True)
        return api.AccessToken(self._api_key, self._api_secret).with_identity(f"agent-{name}").with_name(f"{name} Agent").with_grants(grants).to_jwt()

    async def start(self) -> None:
        """Join the room and bridge audio until the pipeline shuts down.

        On a failed join the participants leave before the error is raised: the edge runner does not call :meth:`stop` then.
        """
        _log.info(f"Connecting to LiveKit room at {self.room_url}")

        self._stop_event = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self._init_producer()
        self._pending = asyncio.Queue(maxsize=_MAX_PENDING_REQUESTS)
        self._sender_task = asyncio.create_task(self._drain_requests())

        already_here: list[str] = []
        try:
            for index, participant in enumerate(self._participants):
                listen = index == 0
                await participant.join(self._new_room(listen), self.room_url, listen)
                if listen:
                    # LiveKit raises participant_connected only for later joins, so callers already here are greeted below.
                    already_here = self._callers_in(participant.room)
        except Exception:
            await self._release()
            raise
        with self._team_lock:
            self._connected = True
            pending, self._pending_team = self._pending_team, None
        if not already_here:
            _log.info(f"No caller is in LiveKit room {self.session_id}; ending the edge")
            self._stop_event.set()
        else:
            _log.info("LiveKit WebRTC connection established; AI audio published.")
            self._show_speaking()
            if pending is not None:
                self._show_team(*pending)
            for identity in already_here:
                self._in_background(self._greet(identity))

        await self._stop_event.wait()
        # One participant's room dropping ends the edge; the others must not stay behind in the room.
        await self._release()

    def _new_room(self, listen: bool) -> "rtc.Room":
        """A room for one participant, with its handlers registered before it connects.

        :param listen: The participant hears the caller, so it handles the room's tracks and chat.
        """
        room = rtc.Room()
        room.on("disconnected", self._on_disconnected)
        if listen:
            room.on("participant_connected", self._on_participant_connected)
            room.on("participant_disconnected", self._on_participant_disconnected)
            room.on("track_subscribed", self._on_track_subscribed)
            room.on("data_received", self._handle_chat_message)
        return room

    def _on_disconnected(self, *args, **kwargs) -> None:
        _log.info(f"LiveKit room {self.room_url} disconnected.")
        if not self._stop_event.is_set():
            self._stop_event.set()

    async def stop(self) -> None:
        """Gracefully disconnect and release resources."""
        _log.info("LiveKitEdgeAdapter shutting down: disconnecting from room")
        await self._release()
        if self._stop_event is not None:
            self._stop_event.set()
        _log.info("LiveKitEdgeAdapter disconnected successfully")

    async def _release(self) -> None:
        """Send the end-of-session control, stop the background work, and take every participant out of the room."""
        await self._send_session_end()
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

    async def _send_session_end(self) -> None:
        """Send the end-of-session control once, behind the frames already staged, so the pool closes the session now.

        Skipped when staged input is still unsent after the wait (the pool would drop it as late input) or the broker
        does not answer in time; the pool's idle eviction closes the session then.
        """
        if self._end_sent or self._producer is None or not self._connected:
            return
        self._end_sent = True
        self._ending = True
        if self._pending is not None and self._sender_task is not None:
            try:
                await asyncio.wait_for(self._pending.join(), timeout=self.SESSION_END_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                _log.warning(
                    f"Staged input for session {self.session_id} was not all sent within {self.SESSION_END_TIMEOUT_SECONDS}s; "
                    "not sending the end-of-session control, which would pass it"
                )
                return
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._producer.enqueue, self.name, self._enqueue(), self.source),
                timeout=self.SESSION_END_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _log.warning(f"The end-of-session control for session {self.session_id} was not accepted within {self.SESSION_END_TIMEOUT_SECONDS}s")
        except Exception as e:
            _log.warning(f"Could not send the end-of-session control for session {self.session_id}: {e}")

    # -- inbound: room -> queue --------------------------------------------------------------

    def _on_participant_connected(self, participant: "rtc.RemoteParticipant") -> None:
        """Open the conversation when a caller joins, before their microphone is published."""
        if participant.identity in self._own_identities:
            return
        self._in_background(self._greet(participant.identity))

    def _on_participant_disconnected(self, participant: "rtc.RemoteParticipant") -> None:
        """A participant left; the last caller leaving stops the edge, which ends the session.

        The edge ends its own call rather than waiting for ``room_finished``: with several IOHandler replicas that webhook
        can reach a process that never hosted this room.
        """
        if participant.identity in self._own_identities or self._stop_event is None:
            return
        # A caller who rejoins while others stay gets greeted again.
        self._greeted.discard(participant.identity)
        # LiveKit removes the participant from the room before raising this event.
        if not self._callers_in(self._participants[0].room):
            _log.info(f"The last caller left room {self.session_id}; ending the session")
            self._stop_event.set()

    def _callers_in(self, room: "rtc.Room | None") -> list[str]:
        """The identities of the callers already in ``room``."""
        participants = getattr(room, "remote_participants", None) or {}
        return [p.identity for p in participants.values() if p.identity not in self._own_identities]

    def _on_track_subscribed(self, track: "rtc.Track", publication: "rtc.RemoteTrackPublication", participant: "rtc.RemoteParticipant") -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if participant.identity in self._own_identities:
            publication.set_subscribed(False)
            return
        _log.info(f"Subscribed to audio track from {participant.identity}")
        asyncio.create_task(self._process_incoming_audio(track, participant.identity))

    async def _greet(self, participant_identity: str) -> None:
        """Kick off the conversation once a participant joins the room."""
        if participant_identity in self._greeted:
            return
        self._greeted.add(participant_identity)
        prompt = self.opening_prompt(participant_identity)
        if not prompt:
            return
        _log.info(f"Triggering auto-greeting for {participant_identity}")
        self._stage_request(AgentRequestText(prompt=prompt), participant_identity)

    def opening_prompt(self, participant_identity: str) -> str | None:
        """The prompt sent when a caller joins the room; override it to open the call differently, or return ``None`` to send nothing.

        :param participant_identity: The identity of the caller who joined.
        """
        return f"A user named {participant_identity} just connected. Say a very short hello to them and confirm you are connected!"

    def _handle_chat_message(self, data_packet: "rtc.DataPacket") -> None:
        if data_packet.topic not in ("chat", "lk-chat-topic", "lk-chat", ""):
            return
        if getattr(data_packet.participant, "identity", None) in self._own_identities:
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
            self._stage_request(AgentRequestText(prompt=text), getattr(data_packet.participant, "identity", None))
        except Exception as e:
            _log.error(f"Failed to process chat: {e}")

    async def _process_incoming_audio(self, track: "rtc.Track", participant_identity: str | None = None) -> None:
        """Pass the caller's audio to the queue, batched per ``execution.realtime.input_batch_ms``.

        Every frame is staged as the participant whose track it is, so the turn runs as them (#603).
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
                    self._stage_request(self._enqueue_audio(raw_bytes), participant_identity)
                    continue
                buffer.extend(raw_bytes)
                if len(buffer) >= self._input_batch_bytes:
                    self._stage_request(self._enqueue_audio(buffer), participant_identity)
                    buffer.clear()
            except Exception as e:
                _log.error(f"Failed to process incoming audio frame: {e}")

        if buffer:
            self._stage_request(self._enqueue_audio(buffer), participant_identity)

    def _stage_request(self, request: AgentRequestText | AgentRequestVoice, participant_identity: str | None = None) -> None:
        """Stage one request for the sender task; a full queue drops it with a warning.

        :param participant_identity: The LiveKit participant it came from, which becomes the
            ``realtime:livekit`` principal's subject with the API key id as its scope (spec #603,
            section 8.4); None stages it anonymous.
        """
        if self._producer is None or self._pending is None or self._ending:
            return

        try:
            self._pending.put_nowait(self._enqueue(request, user_id=participant_identity, namespace=self._api_key))
        except asyncio.QueueFull:
            _log.warning(f"Realtime input queue is full for session {self.session_id}; dropping a frame (broker slow or unreachable?)")

    async def _drain_requests(self) -> None:
        """Send staged requests to the input queue in order, on a worker thread so the room loop never blocks."""
        assert self._pending is not None
        while True:
            inbound = await self._pending.get()
            try:
                await asyncio.to_thread(self._producer.enqueue, self.name, inbound, self.source)
            except Exception as e:
                _log.error(f"Failed to enqueue request for session {self.session_id}: {e}")
            finally:
                self._pending.task_done()

    # -- outbound: queue -> room -------------------------------------------------------------

    async def deliver_chunk(self, chunk: StreamChunk, reply_context: dict[str, str]) -> None:
        """Play one streamed chunk back to the room through the participant speaking.

        The transcript is published as one chat message at the end of the turn. ``InputTranscript`` is ignored;
        override this method to show it.
        """
        if chunk.error:
            self._transcript.clear()
            self._interrupted = False
            self._clear_playback()
            await self.deliver_error(chunk.error, reply_context)
            return

        event = chunk.event
        if event is not None and event.type not in ("agent_changed", "input_transcript"):
            await self._catch_up_speaker()
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
        """Make the participant of ``agent`` the one heard; an agent with no participant yet speaks through the first."""
        self._speaking_agent = agent
        if len(self._participants) == 1:
            return
        speaker = self._by_agent.get(agent)
        if speaker is None:
            fallback = self._participants[0]
            if agent in self._joining:
                _log.info(f"Agent '{agent}' is still joining the room; it speaks through '{fallback.agent}' until it is in")
            elif agent not in self._warned_agents:
                self._warned_agents.add(agent)
                _log.warning(f"Agent '{agent}' has no participant of its own in the room; it speaks through '{fallback.agent}'")
            speaker = fallback
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
                # Drop what is left so it does not trail into the next agent's first words.
                if self._loop is not None:
                    try:
                        self._loop.call_soon_threadsafe(previous.audio_source.clear_queue)
                    except RuntimeError:
                        pass

        _log.info(f"Agent participant speaking: '{previous.agent}' -> '{speaker.agent}'")
        self._set_muted(previous, True)
        self._set_muted(speaker, False)
        self._active = speaker
        self._show_speaking()

    def _set_muted(self, participant: _AgentParticipant, muted: bool) -> None:
        """Mute or unmute the participant's track on the edge's loop, ahead of the audio that follows."""
        if participant.track is None or self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._apply_mute, participant, muted)
        except RuntimeError:
            pass  # the edge's loop has closed

    @staticmethod
    def _apply_mute(participant: _AgentParticipant, muted: bool) -> None:
        track = participant.track
        if track is None:
            return
        try:
            track.mute() if muted else track.unmute()
        except Exception as e:
            _log.warning(f"Could not {'mute' if muted else 'unmute'} agent participant {participant.identity}: {e}")

    async def _catch_up_speaker(self) -> None:
        """Move the speaking agent onto its own participant once that participant has joined."""
        agent = self._speaking_agent
        speaker = self._by_agent.get(agent) if agent else None
        if speaker is not None and speaker is not self._active:
            await self._change_speaker(agent)

    def _show_team(self, starting: str, agents: list[str]) -> None:
        """Give every agent of the team a participant of its own, joining in the background.

        Without ``api_key`` and ``api_secret`` the team speaks through the one participant, with a warning.

        :param starting: The agent the conversation starts with.
        :param agents: Every agent the conversation can hand off to, the starting one first.
        """
        if self._participants[0] not in self._by_agent.values():
            self._by_agent.setdefault(starting, self._participants[0])
        with self._team_lock:
            if not self._connected:
                # Joins that overlap the first one time out and drop the room, so the team waits for it.
                self._pending_team = (starting, agents)
                return
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
            pass  # the edge's loop has closed

    def _join_team(self, names: list[str]) -> None:
        self._in_background(self._update_attribute(self._active))
        for name in names:
            participant = self._AgentParticipant(name, f"agent-{name}", self._mint_token(name))
            self._own_identities.add(participant.identity)
            # Listed before it joins, so a release mid-join takes it out too.
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
        """Run ``coro`` on the edge's loop; cancelled on release."""
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _show_speaking(self) -> None:
        """Set ``ACTIVE_ATTRIBUTE`` on every participant in the background: LiveKit's confirmation can be slow or never come."""
        if self._loop is None or len(self._participants) == 1:
            return
        try:
            self._loop.call_soon_threadsafe(self._start_attribute_updates)
        except RuntimeError:
            pass  # the edge's loop has closed

    def _start_attribute_updates(self) -> None:
        for participant in self._participants:
            if participant.audio_source is not None:
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

    async def deliver(self, reply: AgentReply, reply_context: dict[str, str]) -> None:
        """Publish a completed reply as chat text."""
        text = getattr(reply, "response", "") or str(reply)
        if text:
            await self._publish_text(text)

    async def deliver_error(self, message: str, reply_context: dict[str, str]) -> None:
        """Publish a failure to the room as chat text."""
        await self._publish_text(message)

    async def _publish_text(self, text: str, participant: _AgentParticipant | None = None) -> None:
        """Publish ``text`` as a chat message from ``participant``, by default the one speaking."""
        room = (participant or self._active).room
        if room is None:
            return
        payload = json.dumps({"id": str(uuid.uuid4()), "message": text, "timestamp": 0})
        await self._run_on_room(room.local_participant.publish_data(payload.encode("utf-8"), reliable=True, topic="lk-chat"))

    def _clear_playback(self) -> None:
        """Drop the audio still queued on every participant; runs on the edge's loop, which owns the sources."""
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
        """Await a room coroutine on the edge's loop; deliveries arrive on the Response Handler's thread."""
        if self._loop is None:
            coro.close()
            return
        if self._loop is asyncio.get_running_loop():
            await coro
            return
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        await asyncio.wrap_future(future)


class LiveKitLifecycleAdapter(EdgeLifecycleAdapter):
    """LiveKit's room webhooks as edge lifecycle events, so every room gets its own edge and session.

    ``room_started`` starts a :class:`LiveKitEdgeAdapter` for the room (the room name is the session id); a
    ``participant_joined`` also starts it, so a caller who rejoins during the edge's departure window gets a new edge. The edge
    ends its session when the last caller leaves, and ``room_finished`` stops it if it is still running. Webhooks are verified with
    LiveKit's own ``WebhookReceiver`` over the API key and secret that sign them. Override :meth:`should_start` to
    choose the rooms, or :meth:`create_edge` to build the edge. Hosted by ``EdgeLifecycleRESTRequestHandler``.
    """

    name = "livekit"
    webhook_path = "/livekit/webhook"

    def __init__(self, api_key: str | None = None, api_secret: str | None = None):
        """
        :param api_key: The LiveKit API key that signs the webhooks; defaults to ``livekit.api_key``.
        :param api_secret: The LiveKit API secret; defaults to ``livekit.api_secret``.
        :raises ValueError: If the key or secret is missing.
        """
        config = AKConfig.get().livekit
        key, secret = api_key or config.api_key, api_secret or config.api_secret
        if not (key and secret):
            raise ValueError("LiveKitLifecycleAdapter needs the LiveKit API key and secret (AK_LIVEKIT__API_KEY, AK_LIVEKIT__API_SECRET)")
        self._api_key, self._api_secret = key, secret
        self._receiver = api.WebhookReceiver(api.TokenVerifier(key, secret))

    async def parse(self, raw: Any) -> EdgeLifecycleEvent | None:
        """Verify one LiveKit webhook (the SDK checks the signature while parsing) and map its room event.

        :raises HTTPException: 401 when the signature does not verify.
        """
        from fastapi import HTTPException

        try:
            body = (await raw.body()).decode("utf-8")
            event = self._receiver.receive(body, raw.headers.get("Authorization", ""))
        except Exception as e:
            _log.warning(f"Rejected a LiveKit webhook: {e}")
            raise HTTPException(status_code=401, detail="Invalid LiveKit webhook signature")
        room = event.room.name if event.HasField("room") else ""
        if not room:
            return None
        # The edge's own agent participants also raise participant_joined; they must not start another edge.
        if event.event == "participant_joined" and event.participant.identity.startswith("agent-"):
            return None
        if event.event in ("room_started", "participant_joined"):
            return EdgeLifecycleEvent(room, start=True)
        if event.event == "room_finished":
            return EdgeLifecycleEvent(room, start=False)
        return None

    def create_edge(self, session_id: str) -> LiveKitEdgeAdapter:
        """An edge for the room, signed with the same keys."""
        return LiveKitEdgeAdapter(session_id=session_id, api_key=self._api_key, api_secret=self._api_secret)
