"""PCM16 audio helpers shared by the realtime edge and the framework adapters.

The realtime edge (e.g. the LiveKit gateway) carries PCM16 mono audio at a single rate in both
directions. A model adapter declares the rates its model wants, and the pipeline converts. Keeping
the rate and the resampler here gives every layer one source of truth, without naming any vendor.
"""

import array
import sys

# PCM16 mono, in and out: the rate the realtime edge carries audio at end to end.
EDGE_SAMPLE_RATE = 24000


def resample_pcm16(data: bytes, source_rate: int, target_rate: int) -> bytes:
    """Linearly resample little-endian mono PCM16 audio from ``source_rate`` to ``target_rate``."""
    if not data or source_rate == target_rate:
        return data
    samples = array.array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if not samples:
        return b""
    if sys.byteorder == "big":
        samples.byteswap()

    ratio = source_rate / target_rate
    out_count = int(len(samples) / ratio)
    out = array.array("h", bytes(out_count * 2))
    for i in range(out_count):
        position = i * ratio
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        fraction = position - left
        out[i] = int(samples[left] + (samples[right] - samples[left]) * fraction)

    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()
