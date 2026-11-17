"""Realtime voice: a live, native model session per call (``execution.mode: realtime``).

Agent Kernel carries audio and text between an edge (a LiveKit room) and the framework's own realtime
session (OpenAI ``RealtimeSession`` or ADK ``Runner.run_live()``). The framework runs the tools, not AK.

Call flow::

    edge -> input queue -> RealtimeAgentRunner -> RealtimeConnectionPool -> native session
         -> RealtimeConnectionPool (paced) -> output queue -> ResponseHandler -> edge

Threads:

- **Consumer threads** run ``RealtimeAgentRunner`` and call ``RealtimeConnectionPool.dispatch``. They never
  touch a native session: each send is handed to the pool loop and waited on, bounded.
- **The pool loop thread** (``realtime-pool``) runs every native session, pacing task and close.
- **Response handler threads** deliver each output chunk to the edge, which runs on a thread of its own.

Files: ``base.py`` (``RealtimeRunner`` contract and ``RealtimeRunner.Event``), ``audio.py`` (PCM16 helpers),
``pool.py`` (``RealtimeConnectionPool``), ``connection.py`` (``RealtimeConnection``: one call),
``store.py`` (``RealtimeTurnStore``: the session saved after each turn and at the end), ``testing.py``
(``RealtimeRunnerContract``, for tests of a runner).

Specs: ``docs/specs/405-livekit-realtime-voice/``, ``809-realtime-multi-agent-handoffs/``,
``810-native-realtime-agents/``; identity on a call is ``603-identity-rbac-registry/`` section 8.4.

Exports are lazy (as in ``agentkernel.pipeline.ws``), so importing the contract never loads the pool.
"""

import importlib
from typing import TYPE_CHECKING, Any

_LAZY_EXPORTS = {
    "RealtimeRunner": ".base",
    "EDGE_SAMPLE_RATE": ".audio",
    "PCM16Resampler": ".audio",
    "RealtimeConnection": ".connection",
    "RealtimeConnectionPool": ".pool",
    "RealtimeTurnStore": ".store",
}

__all__ = sorted(_LAZY_EXPORTS)

if TYPE_CHECKING:  # pragma: no cover: static resolution only, preserves laziness at runtime
    from .audio import EDGE_SAMPLE_RATE, PCM16Resampler
    from .base import RealtimeRunner
    from .connection import RealtimeConnection
    from .pool import RealtimeConnectionPool
    from .store import RealtimeTurnStore


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
