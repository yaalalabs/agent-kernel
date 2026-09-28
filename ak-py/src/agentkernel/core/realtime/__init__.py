"""Core building blocks for realtime (persistent-socket) execution.

The framework-agnostic contract every realtime adapter implements, plus the shared PCM16 helpers
(the edge sample rate and a resampler) the pipeline and the edge both use.
"""

from .pcm import EDGE_SAMPLE_RATE, resample_pcm16
from .runner import RealtimeRunner
