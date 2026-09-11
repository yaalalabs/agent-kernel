"""WebRTC leg (aiortc) and the audio pumps between the caller and Gemini Live.

The bridge owns no call policy — ``call_manager`` drives it. aiortc gathers ICE
non-trickle, so ``answer()`` returns a complete SDP answer ready for the Graph
``pre_accept``/``accept`` calls.
"""

from __future__ import annotations

import asyncio
import fractions
import logging
import os
import time

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack
from google.genai import types

from voice.audio import Pcm16Resampler, PlayoutBuffer, pcm_to_frame
from voice.sdp import rewrite_host_candidates, sanitize_answer, summarize

logger = logging.getLogger("sarasavi.voice.bridge")

# aiortc gathers ICE non-trickle: setLocalDescription only returns once every
# candidate resolves, and localDescription is unset before that, so the wait cannot
# simply be capped. STUN is what makes it slow (~5s measured), and its only job is
# discovering our public address. On a 1:1 NAT host (EC2) that address is known in
# advance, so setting SARASAVI_PUBLIC_IP skips STUN altogether and relabels the host
# candidates instead. Without it we fall back to STUN, which still works anywhere.
STUN_URL = os.environ.get("SARASAVI_VOICE_STUN", "stun:stun.l.google.com:19302")
PUBLIC_IP = os.environ.get("SARASAVI_PUBLIC_IP", "").strip()

_WEBRTC_RATE = 48000
_GEMINI_IN_RATE = 16000
_PTIME = 0.02  # 20 ms frames


SDP_DEBUG_PATH = os.environ.get("SARASAVI_SDP_DEBUG_FILE", "voice_sdp_debug.log")


def _dump_sdp(offer_sdp: str, answer_sdp: str) -> None:
    """Append the offer/answer pair to a file.

    Meta rejects a malformed answer with an opaque "SDP Validation error", so the
    only way to debug interop is to read exactly what each side sent.
    """
    try:
        with open(SDP_DEBUG_PATH, "a", encoding="utf-8") as handle:
            handle.write("=" * 30 + " OFFER (from Meta) " + "=" * 30 + "\n")
            handle.write(offer_sdp)
            handle.write("\n" + "=" * 30 + " ANSWER (from aiortc) " + "=" * 30 + "\n")
            handle.write(answer_sdp)
            handle.write("\n\n")
    except Exception:
        logger.exception("Could not write SDP debug dump")


class GeminiPlayoutTrack(MediaStreamTrack):
    """Outbound audio track: paces 20 ms mono frames from the playout buffer.

    Emits silence when the buffer is empty so the RTP stream never stalls.
    """

    kind = "audio"

    def __init__(self, buffer: PlayoutBuffer, sample_rate: int = _WEBRTC_RATE):
        super().__init__()
        self._buffer = buffer
        self._rate = sample_rate
        self._samples = int(sample_rate * _PTIME)
        self._pts = 0
        self._start: float | None = None
        self._frames = 0
        self._voiced = 0

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        if self._start is None:
            self._start = time.monotonic()
        target = self._start + self._pts / self._rate
        delay = target - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

        pending = len(self._buffer)
        pcm = self._buffer.read(self._samples * 2)
        self._frames += 1
        if pending:
            self._voiced += 1
        if self._frames == 1 or self._frames % 250 == 0:  # every 5s
            logger.info(
                "Playout: %d frames sent to caller (%d carried Gemini audio, %d bytes still queued)",
                self._frames,
                self._voiced,
                pending,
            )
        frame = pcm_to_frame(pcm, self._rate)
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, self._rate)
        self._pts += self._samples
        return frame


class RTCBridge:
    """One peer connection answering Meta's SDP offer, plus the two audio pumps."""

    def __init__(self):
        ice_servers = [] if PUBLIC_IP else [RTCIceServer(urls=[STUN_URL])]
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))
        self.playout = PlayoutBuffer()
        # Set on the first audio Gemini produces. The greeting is generated with
        # automatic voice activity detection live, so streaming the caller's mic
        # before it exists lets room noise barge in and cancel it outright.
        self.first_gemini_audio = asyncio.Event()
        self._caller_track: asyncio.Future[MediaStreamTrack] = asyncio.get_running_loop().create_future()
        self._state_events: asyncio.Queue[str] = asyncio.Queue()

        @self.pc.on("track")
        def on_track(track):
            logger.info("Remote track received: kind=%s id=%s", track.kind, track.id)
            if track.kind == "audio" and not self._caller_track.done():
                self._caller_track.set_result(track)

        @self.pc.on("connectionstatechange")
        async def on_state():
            logger.info("Peer connection state: %s", self.pc.connectionState)
            await self._state_events.put(self.pc.connectionState)

    async def answer(self, offer_sdp: str) -> str:
        """Apply Meta's offer, attach the outbound track, return a complete answer."""
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
        self.pc.addTrack(GeminiPlayoutTrack(self.playout))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)  # resolves after ICE gathering
        raw_sdp = self.pc.localDescription.sdp
        if PUBLIC_IP:
            raw_sdp = rewrite_host_candidates(raw_sdp, PUBLIC_IP)
        answer_sdp = sanitize_answer(raw_sdp, offer_sdp)
        logger.info("SDP offer:  %s", summarize(offer_sdp))
        logger.info("SDP answer: %s (raw: %s)", summarize(answer_sdp), summarize(raw_sdp))
        _dump_sdp(offer_sdp, answer_sdp)
        return answer_sdp

    async def wait_connected(self, timeout: float) -> bool:
        """True when the peer connection reaches 'connected' within timeout."""
        if self.pc.connectionState == "connected":
            return True
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                state = await asyncio.wait_for(self._state_events.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return False
            if state == "connected":
                return True
            if state in ("failed", "closed"):
                return False

    async def wait_disconnected(self) -> None:
        """Blocks until the peer connection fails or closes (mid-call drop / hangup)."""
        while True:
            state = await self._state_events.get()
            if state in ("failed", "closed", "disconnected"):
                return

    async def pump_caller_to_gemini(self, live_session) -> None:
        """Caller RTP (48 kHz Opus, decoded by aiortc) -> 16 kHz PCM -> Gemini."""
        logger.info("Inbound pump: waiting for the caller's audio track")
        track = await self._caller_track
        logger.info("Inbound pump: track acquired, streaming caller audio to Gemini")
        resampler = Pcm16Resampler(_GEMINI_IN_RATE)
        frames = sent_bytes = 0
        try:
            while True:
                frame = await track.recv()
                pcm = resampler.resample_frame(frame)
                frames += 1
                if pcm:
                    sent_bytes += len(pcm)
                    await live_session.send_realtime_input(
                        audio=types.Blob(data=pcm, mime_type=f"audio/pcm;rate={_GEMINI_IN_RATE}")
                    )
                if frames == 1 or frames % 250 == 0:  # every 5s
                    logger.info("Inbound: %d frames from caller, %d bytes sent to Gemini", frames, sent_bytes)
        except MediaStreamError:
            logger.info("Caller audio track ended after %d frames", frames)
        except Exception:
            logger.exception("Inbound pump failed after %d frames", frames)
            raise

    async def pump_gemini_to_caller(self, live_session, transcript: list[str], on_tool_call) -> None:
        """Gemini audio (24 kHz) -> 48 kHz playout buffer; flush on barge-in.

        ``on_tool_call`` is an async callable receiving the function_calls list;
        it executes the tools and sends the responses back on the live session.
        """
        resampler = Pcm16Resampler(_WEBRTC_RATE)
        audio_bytes = 0
        messages = 0
        streams = 0
        agent_buf: list[str] = []
        caller_buf: list[str] = []
        logger.info("Outbound pump: listening for Gemini audio")
        while True:
            streams += 1
            # receive() ends at each turn boundary; a stream that ends immediately
            # and repeatedly means the session is broken, not that it is quiet.
            if streams > 1:
                logger.info("Outbound: receive stream #%d (messages so far: %d)", streams, messages)
            async for message in live_session.receive():
                messages += 1
                # Anything we do not explicitly handle is logged once: an error or
                # go-away from the server arrives as an ordinary message and would
                # otherwise vanish, leaving a silent call with no explanation.
                if not (message.server_content or message.data or message.tool_call):
                    if messages <= 5:
                        try:
                            payload = message.model_dump(exclude_none=True)
                        except Exception:
                            payload = repr(message)[:400]
                        logger.info("Outbound: unhandled message: %s", str(payload)[:400])
                server_content = message.server_content
                if server_content is not None:
                    if getattr(server_content, "interrupted", False):
                        self.playout.flush()  # barge-in: drop queued speech
                    if server_content.output_transcription and server_content.output_transcription.text:
                        text = server_content.output_transcription.text
                        transcript.append(f"agent: {text}")
                        agent_buf.append(text)
                    if server_content.input_transcription and server_content.input_transcription.text:
                        text = server_content.input_transcription.text
                        transcript.append(f"caller: {text}")
                        caller_buf.append(text)
                    if getattr(server_content, "turn_complete", False):
                        for who, buf in (("Caller", caller_buf), ("Gemini", agent_buf)):
                            line = "".join(buf).strip()
                            if line:
                                logger.info("%s: %s", who, line)
                            buf.clear()
                if message.data:
                    if audio_bytes == 0:
                        logger.info("Outbound: first Gemini audio chunk (%d bytes)", len(message.data))
                        self.first_gemini_audio.set()
                    audio_bytes += len(message.data)
                    self.playout.write(resampler.resample_pcm(message.data, 24000))
                if message.tool_call and message.tool_call.function_calls:
                    names = [fc.name for fc in message.tool_call.function_calls]
                    logger.info("Outbound: Gemini requested tools %s", names)
                    await on_tool_call(message.tool_call.function_calls)

    async def close(self) -> None:
        try:
            await self.pc.close()
        except Exception:
            logger.exception("Peer connection close failed")
