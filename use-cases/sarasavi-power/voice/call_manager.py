"""Call lifecycle: RINGING -> CONNECTING -> ACTIVE -> ENDING -> DONE.

``CallManager`` owns capacity and per-call sessions; ``CallSession`` drives one
call. All I/O (Graph signaling, WebRTC, Gemini) is injected so the state machine
is unit-testable with fakes.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import os
import time
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger("sarasavi.voice.calls")

MAX_CALLS = int(os.environ.get("SARASAVI_MAX_CALLS", "2"))
CALL_MAX_SECONDS = float(os.environ.get("SARASAVI_CALL_MAX_SECONDS", "600"))
CONNECT_TIMEOUT_SECONDS = 15.0
# How long to hold the caller mic closed while the greeting is generated.
GREETING_TIMEOUT_SECONDS = 4.0
# Gemini's goodbye audio is already queued in the playout buffer by the time the
# end_call function call arrives (same message stream, in order), but the buffer
# still needs real time to drain over the RTP track before it is safe to hang up.
END_CALL_GRACE_SECONDS = float(os.environ.get("SARASAVI_END_CALL_GRACE_SECONDS", "2.5"))

GREETING_TURN = (
    "[The call just connected and the caller is listening. Say your one-line "
    "opening now, in Sinhala, and keep it under four seconds. Do not explain "
    "what you can do until they ask.]"
)

BUSY_MESSAGE = (
    "Sorry, our lines are busy right now. Please type your question here instead. "
    "සමාවන්න, දැන් අපේ line busy. කරුණාකර ප්‍රශ්නය මෙතන type කරන්න."
)


class CallState(str, Enum):
    RINGING = "ringing"
    CONNECTING = "connecting"
    ACTIVE = "active"
    ENDING = "ending"
    DONE = "done"


class CallSession:
    """One live call. Collaborators are injected:

    calls_api      pre_accept/accept/terminate (see voice.calls_api)
    bridge         answer/wait_connected/pumps/close (see voice.bridge)
    live_connect   async context manager -> Gemini live session
    executor       VoiceToolExecutor for this caller
    on_done        async callback (self) -> None, fired exactly once from close()
    """

    def __init__(
        self,
        call_id: str,
        from_number: str,
        offer_sdp: str,
        *,
        calls_api,
        bridge,
        live_connect,
        executor,
        on_done: Callable[["CallSession"], Awaitable[None]] | None = None,
        max_seconds: float = CALL_MAX_SECONDS,
    ):
        self.call_id = call_id
        self.from_number = from_number
        self.offer_sdp = offer_sdp
        self.state = CallState.RINGING
        self.transcript: list[str] = []
        self.tools_used: list[str] = []
        self._calls_api = calls_api
        self._bridge = bridge
        self._live_connect = live_connect
        self._executor = executor
        self._on_done = on_done
        self._max_seconds = max_seconds
        self._tasks: list[asyncio.Task] = []
        self._closed = False
        # Set by the end_call tool: the agent judged the conversation finished
        # and wants to hang up on its own, rather than leaving the line open
        # until the caller hangs up or the max-duration timeout fires.
        self._end_requested = asyncio.Event()
        # Wall-clock start and duration, for the post-call service record.
        self.started_at = datetime.datetime.now(datetime.timezone.utc)
        self.duration_seconds: float | None = None
        self._monotonic_start = time.monotonic()

    async def run(self) -> None:
        """Drive the call to completion. Never raises; always ends in DONE."""
        started = time.monotonic()

        def elapsed() -> str:
            return f"{time.monotonic() - started:.2f}s"

        async with contextlib.AsyncExitStack() as stack:
            # Open the Gemini session while ICE gathering and the two Graph
            # round-trips are still in flight — the caller hears the greeting
            # ~2s sooner than opening it after signaling completes.
            live_task = asyncio.create_task(stack.enter_async_context(self._live_connect()))
            stack.push_async_callback(self._discard_live_task, live_task)
            try:
                logger.info("Call %s: building SDP answer", self.call_id)
                answer_sdp = await self._bridge.answer(self.offer_sdp)
                logger.info("Call %s: answer ready (%s bytes) at %s", self.call_id, len(answer_sdp), elapsed())
                self.state = CallState.CONNECTING
                if not await self._calls_api.pre_accept(self.call_id, answer_sdp):
                    await self.close("pre_accept failed")
                    return
                logger.info("Call %s: pre_accept ok at %s", self.call_id, elapsed())
                if not await self._calls_api.accept(self.call_id, answer_sdp):
                    await self.close("accept failed")
                    return
                logger.info("Call %s: accept ok at %s; waiting for media", self.call_id, elapsed())
                if not await self._bridge.wait_connected(CONNECT_TIMEOUT_SECONDS):
                    await self._calls_api.terminate(self.call_id)
                    await self.close("media never connected")
                    return

                self.state = CallState.ACTIVE
                logger.info("Call %s: media connected at %s", self.call_id, elapsed())
                live = await live_task
                logger.info("Call %s: Gemini Live session ready at %s", self.call_id, elapsed())
                # Order matters. Start listening to Gemini, ask for the greeting,
                # and only then open the caller's microphone: Gemini's automatic
                # voice activity detection treats inbound audio as barge-in, so a
                # mic opened first lets ordinary room noise cancel the greeting
                # before a single sample is produced. That is what left callers in
                # silence until they happened to speak.
                outbound = asyncio.create_task(
                    self._bridge.pump_gemini_to_caller(live, self.transcript, self._make_tool_handler(live))
                )
                await self._greet(live)
                try:
                    await asyncio.wait_for(self._bridge.first_gemini_audio.wait(), timeout=GREETING_TIMEOUT_SECONDS)
                    logger.info("Call %s: greeting audio flowing at %s", self.call_id, elapsed())
                except asyncio.TimeoutError:
                    # Opening the mic anyway beats a dead line.
                    logger.warning("Call %s: no greeting audio after %ss", self.call_id, GREETING_TIMEOUT_SECONDS)

                pumps = [
                    outbound,
                    asyncio.create_task(self._bridge.pump_caller_to_gemini(live)),
                    asyncio.create_task(self._watch_disconnect()),
                    asyncio.create_task(self._end_requested.wait()),
                ]
                self._tasks = pumps
                done, _ = await asyncio.wait(pumps, timeout=self._max_seconds, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    reason = "max duration reached"
                elif self._end_requested.is_set():
                    reason = "agent ended the call"
                else:
                    reason = "media or model stream ended"
                # A pump that dies takes the call down; without this the cause is lost.
                for task in done:
                    if not task.cancelled() and task.exception():
                        logger.error("Call %s: pump failed", self.call_id, exc_info=task.exception())
                        reason = "audio pump failed"
                await self._calls_api.terminate(self.call_id)
                await self.close(reason)
            except Exception:
                logger.exception("Call %s crashed", self.call_id)
                await self._calls_api.terminate(self.call_id)
                await self.close("internal error")

    @staticmethod
    async def _discard_live_task(task: asyncio.Task) -> None:
        """Cancel a still-pending Gemini connect when signaling failed first."""
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _greet(self, live) -> None:
        """Ask Gemini to open the call; the caller hears the greeting first."""
        try:
            await live.send_client_content(
                turns={"role": "user", "parts": [{"text": GREETING_TURN}]},
                turn_complete=True,
            )
            logger.info("Call %s: greeting turn sent", self.call_id)
        except Exception:
            logger.exception("Greeting turn failed")

    def _make_tool_handler(self, live):
        async def handle(function_calls) -> None:
            from google.genai import types

            responses = []
            end_requested = False
            for fc in function_calls:
                self.tools_used.append(fc.name)
                if fc.name == "end_call":
                    # Not a household tool: it does not touch stored state, so it
                    # never goes through VoiceToolExecutor.
                    end_requested = True
                    result = {"ok": True}
                else:
                    result = await self._executor.call(fc.name, dict(fc.args or {}))
                responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
            await live.send_tool_response(function_responses=responses)
            if end_requested:
                await asyncio.sleep(END_CALL_GRACE_SECONDS)
                self._end_requested.set()

        return handle

    async def _watch_disconnect(self) -> None:
        await self._bridge.wait_disconnected()

    async def handle_terminate_event(self) -> None:
        """Webhook said the user hung up."""
        await self.close("caller hung up")

    async def close(self, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        self.duration_seconds = time.monotonic() - self._monotonic_start
        self.state = CallState.ENDING
        logger.info("Call %s ending: %s", self.call_id, reason)
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self._bridge.close()
        self.state = CallState.DONE
        if self._on_done:
            try:
                await self._on_done(self)
            except Exception:
                logger.exception("Post-call handling failed for %s", self.call_id)


class CallManager:
    """Routes `calls` webhook events; enforces the concurrent-call cap."""

    def __init__(
        self,
        calls_api,
        session_factory: Callable[[str, str, str], CallSession],
        send_text: Callable[[str, str], Awaitable[None]] | None = None,
        max_calls: int = MAX_CALLS,
    ):
        self._calls_api = calls_api
        self._session_factory = session_factory
        self._send_text = send_text
        self._max_calls = max_calls
        self._active: dict[str, CallSession] = {}

    @property
    def active_calls(self) -> int:
        return len(self._active)

    async def handle_call_event(self, call: dict[str, Any]) -> None:
        event = call.get("event")
        call_id = call.get("id")
        if not call_id:
            logger.warning("Call event without id: %s", call)
            return
        if event == "connect":
            await self._handle_connect(call)
        elif event == "terminate":
            session = self._active.get(call_id)
            if session:
                await session.handle_terminate_event()
        else:
            logger.debug("Ignoring call event %s for %s", event, call_id)

    async def _handle_connect(self, call: dict[str, Any]) -> None:
        call_id = call["id"]
        from_number = call.get("from", "")
        offer_sdp = (call.get("session") or {}).get("sdp", "")
        if not offer_sdp:
            logger.warning("Connect event for %s carries no SDP offer", call_id)
            return
        if len(self._active) >= self._max_calls:
            logger.info("Rejecting call %s: %d active calls", call_id, len(self._active))
            await self._calls_api.reject(call_id)
            if self._send_text and from_number:
                await self._send_text(from_number, BUSY_MESSAGE)
            return

        logger.info("Accepting call %s from %s", call_id, from_number)
        session = self._session_factory(call_id, from_number, offer_sdp)
        self._active[call_id] = session

        async def run_and_release():
            try:
                await session.run()
            finally:
                self._active.pop(call_id, None)

        asyncio.create_task(run_and_release())
