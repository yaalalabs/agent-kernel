"""Reproduce the silent-call symptom without placing a WhatsApp call.

A live call differs from devtools/voice_loopback.py in exactly one way: it streams
realtime audio into the session while waiting for the greeting. This script runs
both variants so the difference is attributable.

  uv run python devtools/voice_repro.py greeting-only
  uv run python devtools/voice_repro.py with-audio
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from google import genai
from google.genai import types

from voice.live_agent import LIVE_MODEL, build_live_config

# Imported, not copied: a stale duplicate here made the harness test a greeting
# the real call no longer sends.
from voice.call_manager import GREETING_TURN as GREETING

SILENCE_20MS = b"\x00\x00" * 320  # 20 ms of 16 kHz mono PCM16, as the bridge sends


async def pump_silence(session, noisy: bool = False) -> None:
    """Mimic the bridge: a 20 ms frame every 20 ms, forever."""
    n = 0
    while True:
        data = noise_20ms(n) if noisy else SILENCE_20MS
        n += 1
        await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
        await asyncio.sleep(0.02)


async def main(mode: str) -> None:
    client = genai.Client()
    audio_bytes = 0
    events: list[str] = []

    if mode == "as-call":
        # Exactly how call_manager opens it: entered from a short-lived task via an
        # AsyncExitStack, ~2s before the greeting, with the pumps in their own tasks.
        import contextlib

        async with contextlib.AsyncExitStack() as stack:
            live_task = asyncio.create_task(
                stack.enter_async_context(client.aio.live.connect(model=LIVE_MODEL, config=build_live_config()))
            )
            await asyncio.sleep(2)  # signaling happens here in a real call
            session = await live_task
            print("session open via AsyncExitStack task")
            await session.send_client_content(turns={"role": "user", "parts": [{"text": GREETING}]}, turn_complete=True)
            print("greeting sent")

            async def read_call() -> None:
                nonlocal audio_bytes
                while True:
                    async for message in session.receive():
                        sc = message.server_content
                        if sc is not None:
                            if sc.output_transcription and sc.output_transcription.text:
                                events.append(f"out:{sc.output_transcription.text}")
                        if message.data:
                            audio_bytes += len(message.data)

            tasks = [asyncio.create_task(read_call()), asyncio.create_task(pump_silence(session))]
            await asyncio.wait(tasks, timeout=15, return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()

        print(f"audio received from Gemini: {audio_bytes} bytes")
        print(f"events: {events[:12]}")
        print("VERDICT:", "MODEL SPOKE" if audio_bytes else "SILENT")
        return

    async with client.aio.live.connect(model=LIVE_MODEL, config=build_live_config()) as session:
        print(f"session open ({LIVE_MODEL}); mode={mode}")
        await session.send_client_content(turns={"role": "user", "parts": [{"text": GREETING}]}, turn_complete=True)
        print("greeting sent")

        silence = (
            asyncio.create_task(pump_silence(session, noisy=(mode == "with-noise")))
            if mode in ("with-audio", "with-noise")
            else None
        )

        async def read() -> None:
            nonlocal audio_bytes
            async for message in session.receive():
                sc = message.server_content
                if sc is not None:
                    if getattr(sc, "interrupted", False):
                        events.append("INTERRUPTED")
                    if sc.output_transcription and sc.output_transcription.text:
                        events.append(f"out:{sc.output_transcription.text}")
                    if sc.input_transcription and sc.input_transcription.text:
                        events.append(f"in:{sc.input_transcription.text}")
                if message.data:
                    audio_bytes += len(message.data)

        try:
            await asyncio.wait_for(read(), timeout=15)
        except asyncio.TimeoutError:
            pass
        finally:
            if silence:
                silence.cancel()

    print(f"audio received from Gemini: {audio_bytes} bytes")
    print(f"events: {events[:12]}")
    print("VERDICT:", "MODEL SPOKE" if audio_bytes else "SILENT")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "greeting-only"))
