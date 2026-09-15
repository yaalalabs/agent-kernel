"""PCM16 mono audio helpers for the call bridge.

WhatsApp's WebRTC leg decodes to 48 kHz; Gemini Live wants 16 kHz in and returns
24 kHz out. Both directions resample through PyAV (bundled with aiortc) — no
numpy dependency, so frames are read straight from plane bytes.
"""

from __future__ import annotations

import fractions

import av

BYTES_PER_SAMPLE = 2  # s16 mono


def frame_to_pcm(frame: av.AudioFrame) -> bytes:
    """Extract tightly-packed PCM16 bytes from a mono s16 frame (planes are padded)."""
    return bytes(frame.planes[0])[: frame.samples * BYTES_PER_SAMPLE]


def pcm_to_frame(pcm: bytes, sample_rate: int) -> av.AudioFrame:
    """Wrap tightly-packed PCM16 mono bytes in an AudioFrame."""
    frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // BYTES_PER_SAMPLE)
    frame.planes[0].update(pcm)
    frame.sample_rate = sample_rate
    return frame


class Pcm16Resampler:
    """Stateful mono PCM16 resampler (keeps filter state across chunks)."""

    def __init__(self, out_rate: int):
        self._out_rate = out_rate
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=out_rate)
        self._next_pts = 0

    @property
    def out_rate(self) -> int:
        return self._out_rate

    def resample_frame(self, frame: av.AudioFrame) -> bytes:
        """Resample one decoded frame (any rate/layout) to mono PCM16 at out_rate."""
        # aiortc delivers frames with increasing pts; the resampler requires them.
        frames = self._resampler.resample(frame)
        return b"".join(frame_to_pcm(f) for f in frames)

    def resample_pcm(self, pcm: bytes, in_rate: int) -> bytes:
        """Resample raw mono PCM16 bytes at in_rate to out_rate."""
        frame = pcm_to_frame(pcm, in_rate)
        frame.pts = self._next_pts
        frame.time_base = fractions.Fraction(1, in_rate)
        self._next_pts += frame.samples
        frames = self._resampler.resample(frame)
        return b"".join(frame_to_pcm(f) for f in frames)


class PlayoutBuffer:
    """Byte FIFO between the Gemini receive loop and the outbound WebRTC track.

    Single-event-loop use only (no locks). ``read`` zero-pads when drained so the
    track can keep emitting silence, and ``flush`` implements barge-in.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def __len__(self) -> int:
        return len(self._buffer)

    def write(self, data: bytes) -> None:
        self._buffer.extend(data)

    def read(self, size: int) -> bytes:
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        if len(chunk) < size:
            chunk += b"\x00" * (size - len(chunk))
        return chunk

    def flush(self) -> None:
        self._buffer.clear()
