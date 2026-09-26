import asyncio
import base64
import json
import logging
import uuid
from typing import Dict, Optional

from ...core.model import AgentReply, AgentRequestText, AgentRequestVoice, BaseRunRequest, StreamChunk
from ...core.util.factory import AKConfigError
from ...pipeline.envelope import ATTR_INTEGRATION, REPLY_CONTEXT_PREFIX
from ...pipeline.producer import RequestProducer
from ..adapter.base import GatewayAdapter

_log = logging.getLogger("ak.integration.livekit")

INTEGRATION_NAME = "livekit"
# OpenAI Realtime speaks PCM16 at 24 kHz mono in both directions.
AUDIO_SAMPLE_RATE = 24000


try:
    from livekit import rtc
except ImportError:
    rtc = None  # type: ignore


class LiveKitEdgeGateway(GatewayAdapter):
    """Bridges a LiveKit WebRTC room with the Agent Kernel queue.

    Unlike standard messaging webhook adapters which are stateless and split into Inbound/Outbound
    halves, WebRTC requires a stateful, persistent connection to a room. This gateway owns that
    connection: it pushes user audio and chat text to the input queue, and — as the ``livekit``
    outbound adapter — plays the agent's streamed audio and transcript back to the room. It is
    hosted by ``GatewayRunner``, which registers it as the ``livekit`` outbound adapter on start.
    """

    name = INTEGRATION_NAME

    def __init__(
        self,
        room_url: Optional[str] = None,
        agent_name: Optional[str] = None,
        session_id: Optional[str] = None,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        if rtc is None:
            raise AKConfigError("LiveKit SDK is not installed. Run: pip install livekit-api livekit")

        from ...core.config import AKConfig

        config = AKConfig.get()
        self.room_url = room_url or config.livekit.livekit_url
        self.agent_name = agent_name or config.livekit.agent or "general"
        self.session_id = session_id or str(uuid.uuid4())

        if token:
            self.token = token
        else:
            final_api_key = api_key or config.livekit.api_key
            final_api_secret = api_secret or config.livekit.api_secret

            if final_api_key and final_api_secret:
                from livekit import api

                self.token = (
                    api.AccessToken(final_api_key, final_api_secret)
                    .with_identity(f"agent-{self.agent_name}")
                    .with_name(f"{self.agent_name} Agent")
                    .with_grants(api.VideoGrants(room_join=True, room=self.session_id))
                    .to_jwt()
                )
            else:
                raise ValueError("Either 'token' or both 'api_key' and 'api_secret' must be provided in code or config")

        self.room: Optional["rtc.Room"] = None
        self.audio_source: Optional["rtc.AudioSource"] = None
        self.producer: Optional[RequestProducer] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False
        # Accumulated from TextDelta chunks; published as one chat message when the turn ends.
        self._transcript: list[str] = []
        self._interrupted = False

    async def start(self) -> None:
        """Connect to the LiveKit room and bridge audio until the pipeline shuts down."""
        _log.info(f"Connecting to LiveKit room at {self.room_url}")

        self._loop = asyncio.get_running_loop()
        self.room = rtc.Room()
        self.producer = RequestProducer()

        @self.room.on("track_subscribed")
        def on_track_subscribed(track: "rtc.Track", publication: "rtc.RemoteTrackPublication", participant: "rtc.RemoteParticipant"):
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            _log.info(f"Subscribed to audio track from {participant.identity}")
            asyncio.create_task(self._greet(participant.identity))
            asyncio.create_task(self._process_incoming_audio(track))

        @self.room.on("data_received")
        def on_data_received(data_packet: "rtc.DataPacket"):
            self._handle_chat_message(data_packet)

        await self.room.connect(self.room_url, self.token)
        self._connected = True
        _log.info("LiveKit WebRTC connection established.")

        _log.info("Publishing AI audio track to LiveKit...")
        source = rtc.AudioSource(sample_rate=AUDIO_SAMPLE_RATE, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("ai-voice", source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        try:
            await asyncio.wait_for(self.room.local_participant.publish_track(track, options), timeout=10.0)
            _log.info("AI audio track published successfully.")
        except asyncio.TimeoutError:
            _log.error("Timed out waiting for publish_track!")
        except Exception as e:
            _log.error(f"Failed to publish track: {e}")
        self.audio_source = source

        from ...pipeline.thread_runner import ThreadRunner

        _log.info("Entering LiveKitEdgeGateway main wait loop...")
        while not ThreadRunner.shutdown_event.is_set():
            await asyncio.sleep(0.5)

        _log.info("LiveKitEdgeGateway shutting down: disconnecting from room")
        await self.room.disconnect()
        _log.info("LiveKitEdgeGateway disconnected successfully")

    # -- inbound: room -> queue --------------------------------------------------------------

    async def _greet(self, participant_identity: str) -> None:
        """Kick off the conversation once a participant's mic appears."""
        _log.info(f"Triggering auto-greeting for {participant_identity}")
        prompt = f"A user named {participant_identity} just connected their microphone. Say a very short hello to them and confirm you are connected!"
        self._enqueue(AgentRequestText(prompt=prompt, name=self.agent_name))

    def _handle_chat_message(self, data_packet: "rtc.DataPacket") -> None:
        if data_packet.topic not in ("chat", "lk-chat-topic", "lk-chat", ""):
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
            self._enqueue(AgentRequestText(prompt=text, name=self.agent_name))
        except Exception as e:
            _log.error(f"Failed to process chat: {e}")

    async def _process_incoming_audio(self, track: "rtc.Track") -> None:
        """Pass continuous mic audio to the queue, batching frames to prevent thread starvation."""
        audio_stream = rtc.AudioStream(track, sample_rate=AUDIO_SAMPLE_RATE, num_channels=1)
        _log.info("Listening for audio stream (with 100ms batching)...")

        buffer = bytearray()

        async for event in audio_stream:
            try:
                raw_bytes = event.frame.data.tobytes()
                if raw_bytes:
                    buffer.extend(raw_bytes)

                    # Flush to the queue when buffer reaches ~100ms of audio
                    # 24000 samples/sec * 2 bytes/sample * 1 channel * 0.1s = 4800 bytes
                    if len(buffer) >= 4800:
                        b64_audio = base64.b64encode(buffer).decode("utf-8")
                        self._enqueue(AgentRequestVoice(prompt="", audio_data=b64_audio, name=self.agent_name))
                        buffer.clear()
            except Exception as e:
                _log.error(f"Failed to process incoming audio frame: {e}")

        if buffer:
            b64_audio = base64.b64encode(buffer).decode("utf-8")
            self._enqueue(AgentRequestVoice(prompt="", audio_data=b64_audio, name=self.agent_name))

    def _enqueue(self, request) -> None:
        """Push one request onto the input queue tagged for this livekit session."""
        if self.producer is None:
            return
        body = BaseRunRequest(prompt="", session_id=self.session_id, requests=[request])
        request_id = str(uuid.uuid4())
        attributes = {ATTR_INTEGRATION: INTEGRATION_NAME, f"{REPLY_CONTEXT_PREFIX}session_id": self.session_id}
        asyncio.create_task(
            asyncio.to_thread(self.producer.enqueue, body=body, request_id=request_id, attributes=attributes, group_id=self.session_id)
        )

    # -- outbound: queue -> room -------------------------------------------------------------

    async def deliver_chunk(self, chunk: StreamChunk, reply_context: Dict[str, str]) -> None:
        """Play one streamed ``StreamChunk`` back to the room.

        Audio deltas play immediately; transcript deltas are accumulated and published as one
        chat message when the turn's ``done`` chunk arrives; a barge-in ``Interrupt`` clears
        playback and drops the partial transcript.
        """
        event = chunk.event
        if event is not None:
            if event.type == "audio_delta":
                audio_bytes = base64.b64decode(event.content)
                if audio_bytes:
                    frame = rtc.AudioFrame(
                        data=audio_bytes,
                        sample_rate=AUDIO_SAMPLE_RATE,
                        num_channels=1,
                        samples_per_channel=len(audio_bytes) // 2,
                    )
                    await self._run_on_room(self.audio_source.capture_frame(frame))
            elif event.type == "text_delta":
                self._transcript.append(event.content)
            elif event.type == "interrupt":
                # Barge-in: stop buffered AI audio and don't publish a half-said sentence.
                _log.info("Barge-in detected: clearing buffered AI audio")
                self._interrupted = True
                self._clear_playback()

        if chunk.done:
            transcript = "".join(self._transcript).strip()
            self._transcript.clear()
            if self._interrupted:
                self._interrupted = False
                self._clear_playback()
            elif transcript:
                _log.info(f"AI response: {transcript}")
                await self._publish_text(transcript)

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        """Publish a completed reply as chat text (used for the non-streamed fallback path)."""
        text = getattr(reply, "response", "") or str(reply)
        if text:
            await self._publish_text(text)

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        """Surface a failure to the room so the user is never left silent."""
        await self._publish_text(message)

    async def _publish_text(self, text: str) -> None:
        if self.room is None:
            return
        payload = json.dumps({"id": str(uuid.uuid4()), "message": text, "timestamp": 0})
        await self._run_on_room(self.room.local_participant.publish_data(payload.encode("utf-8"), reliable=True, topic="lk-chat"))

    def _clear_playback(self) -> None:
        """Drop AI audio still queued on the LiveKit source so a barge-in cuts it off.

        Called from the Response Handler thread; ``clear_queue`` is synchronous and must run on
        the gateway's own loop, so it is marshalled across with ``call_soon_threadsafe``.
        """
        if self.audio_source is None or self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self.audio_source.clear_queue)
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
