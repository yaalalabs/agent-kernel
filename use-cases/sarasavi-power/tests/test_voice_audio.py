"""Keyless tests for the call bridge's audio path (resampling, playout, pacing)."""

from __future__ import annotations

import asyncio

import pytest
from aiortc.mediastreams import MediaStreamError

from voice.audio import PlayoutBuffer, Pcm16Resampler, frame_to_pcm, pcm_to_frame
from voice.bridge import GeminiPlayoutTrack


def _sine_pcm(samples: int) -> bytes:
    import math

    return b"".join(int(3000 * math.sin(i / 10)).to_bytes(2, "little", signed=True) for i in range(samples))


def test_downsample_48k_to_16k_keeps_one_third_of_samples() -> None:
    resampler = Pcm16Resampler(16000)

    total_out = sum(len(resampler.resample_pcm(_sine_pcm(960), 48000)) for _ in range(20))

    expected = 20 * 960 * 2 / 3  # bytes
    assert abs(total_out - expected) < 960  # resampler latency < one frame


def test_upsample_24k_to_48k_doubles_samples() -> None:
    resampler = Pcm16Resampler(48000)

    total_out = sum(len(resampler.resample_pcm(_sine_pcm(480), 24000)) for _ in range(20))

    expected = 20 * 480 * 2 * 2
    assert abs(total_out - expected) < 960


def test_frame_pcm_round_trip() -> None:
    pcm = _sine_pcm(960)

    frame = pcm_to_frame(pcm, 48000)

    assert frame.samples == 960
    assert frame.sample_rate == 48000
    assert frame_to_pcm(frame) == pcm


def test_playout_buffer_pads_with_silence_and_flushes() -> None:
    buffer = PlayoutBuffer()
    buffer.write(b"\x01\x02")

    chunk = buffer.read(6)

    assert chunk == b"\x01\x02\x00\x00\x00\x00"
    buffer.write(b"\x03" * 10)
    buffer.flush()
    assert len(buffer) == 0
    assert buffer.read(4) == b"\x00" * 4


def test_playout_track_emits_paced_20ms_frames() -> None:
    async def scenario():
        buffer = PlayoutBuffer()
        buffer.write(_sine_pcm(960))
        track = GeminiPlayoutTrack(buffer)

        first = await track.recv()
        second = await track.recv()  # buffer empty -> silence

        assert first.samples == 960
        assert first.sample_rate == 48000
        assert second.pts == 960
        assert frame_to_pcm(second) == b"\x00" * 1920

        track.stop()
        with pytest.raises(MediaStreamError):
            await track.recv()

    asyncio.run(scenario())
