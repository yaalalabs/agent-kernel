"""Keyed dev harness for the voice stack — no Meta account required.

Modes:
  --wav in.wav        Feed a recorded prompt (any rate/mono/stereo WAV) straight
                      into the Gemini Live agent (bypassing WebRTC), save the
                      spoken reply to out.wav, and print transcripts + tool calls.
                      Validates the Live config, Sinhala/Tamil quality, and the
                      VoiceToolExecutor against a real session.
  --text "..."        Same, but sends a text turn instead of audio (fastest check).

Requires GOOGLE_API_KEY in .env. Usage:
  uv run python devtools/voice_loopback.py --text "mage bill eka kiyada?"
  uv run python devtools/voice_loopback.py --wav sinhala_question.wav
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from google import genai
from google.genai import types

SESSION_PHONE = "loopback-tester"


def _read_wav_as_pcm16_mono(path: str, target_rate: int = 16000) -> bytes:
    from voice.audio import Pcm16Resampler

    with wave.open(path, "rb") as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise SystemExit("Only 16-bit PCM WAV files are supported")
    if channels == 2:  # crude downmix: take the left channel
        frames = b"".join(frames[i : i + 2] for i in range(0, len(frames), 4))
    if rate == target_rate:
        return frames
    return Pcm16Resampler(target_rate).resample_pcm(frames, rate)


def _write_wav(path: str, pcm: bytes, rate: int = 24000) -> None:
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


async def run(args: argparse.Namespace) -> None:
    # Register the agent module so Runtime.current() has agents + session store.
    from agentkernel.adk import GoogleADKModule

    from agent import AGENTS
    from voice.live_agent import LIVE_MODEL, VoiceToolExecutor, build_live_config

    GoogleADKModule(AGENTS)
    executor = VoiceToolExecutor(SESSION_PHONE)

    client = genai.Client()
    print(f"Connecting to {LIVE_MODEL} ...")
    reply_pcm = bytearray()
    transcript: list[str] = []

    async with client.aio.live.connect(model=LIVE_MODEL, config=build_live_config()) as live:
        if args.wav:
            pcm = _read_wav_as_pcm16_mono(args.wav)
            print(f"Sending {len(pcm) // 32000:.1f}s of audio from {args.wav}")
            await live.send_realtime_input(audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
            await live.send_realtime_input(audio_stream_end=True)
        else:
            await live.send_client_content(turns={"role": "user", "parts": [{"text": args.text}]}, turn_complete=True)

        # Each live.receive() iteration ends at a turn boundary; a tool response
        # starts a fresh model turn, so keep iterating until audio stops coming.
        for _turn in range(6):  # safety bound
            saw_tool_call = False
            async for message in live.receive():
                if message.data:
                    reply_pcm.extend(message.data)
                content = message.server_content
                if content is not None:
                    if content.output_transcription and content.output_transcription.text:
                        transcript.append(f"agent: {content.output_transcription.text}")
                    if content.input_transcription and content.input_transcription.text:
                        transcript.append(f"caller: {content.input_transcription.text}")
                if message.tool_call and message.tool_call.function_calls:
                    saw_tool_call = True
                    responses = []
                    for fc in message.tool_call.function_calls:
                        print(f"TOOL CALL: {fc.name}({dict(fc.args or {})})")
                        result = await executor.call(fc.name, dict(fc.args or {}))
                        print(f"TOOL RESULT: {result}")
                        responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
                    await live.send_tool_response(function_responses=responses)
            if not saw_tool_call:
                break

    print("\n--- transcript ---")
    for line in transcript:
        print(line)
    if reply_pcm:
        _write_wav(args.out, bytes(reply_pcm))
        print(f"\nSpoken reply written to {args.out} ({len(reply_pcm) // 48000:.1f}s)")
    else:
        print("\nNo audio came back — check the model name and API key.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--wav", help="16-bit PCM WAV file with the caller's question")
    group.add_argument("--text", help="text question to send instead of audio")
    parser.add_argument("--out", default="loopback_reply.wav", help="where to write the spoken reply")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
