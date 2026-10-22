from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Callable

from ..base import Agent, Runner, Session
from ..event import StreamEvent
from ..model import AgentReply, AgentRequest
from .pcm import EDGE_SAMPLE_RATE


class RealtimeRunner(Runner):
    """Base class for framework adapters that run a live, persistent conversation through the
    framework's own realtime runner (the OpenAI Agents SDK's ``RealtimeSession``, ADK's
    ``Runner.run_live``).

    ``input_sample_rate`` and ``output_sample_rate`` are the PCM16 mono rates the model wants. The
    pipeline converts between these and :data:`~agentkernel.core.realtime.pcm.EDGE_SAMPLE_RATE`, so
    an adapter never resamples and no adapter hardcodes the edge's rate.

    The realtime pool creates one instance per session connection, so an instance may keep that
    connection's native session and state on ``self``. The framework owns the conversation: which
    agent is speaking, its tools and their results, handoffs and the model connection. The pool owns
    what is around it: audio pacing, barge-in delivery, queue emission and eviction. An adapter only
    feeds caller input to the native session and reports what the native session produces through
    the ``callback`` given to :meth:`connect`, which is why an adapter never imports pipeline types.

    There is deliberately no tool hook: a framework runs its tools itself. A runner that reports a
    ``tool_call`` event fails the connection, since nothing here would run the tool.

    Bring your own adapter by passing its class as ``realtime_runner_cls`` to the framework's
    ``Module``.
    """

    input_sample_rate: int = EDGE_SAMPLE_RATE
    output_sample_rate: int = EDGE_SAMPLE_RATE

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """Not supported for realtime runners."""
        raise NotImplementedError("Realtime runners do not support unary run().")

    @staticmethod
    async def _cancel_and_wait(task: asyncio.Task | None) -> None:
        """Cancel a background task of the adapter (its socket listener) and wait for it to end.

        Waiting means nothing the task was doing outlives the call that stopped it. A no-op for
        None, and for the calling task itself, which cannot wait for its own end.
        """
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.wait({task})

    def team(self, agent: "Agent") -> list[str]:
        """The names of every speaking agent a conversation with ``agent`` can reach, known up front.

        Read before connecting and announced with the first speaker, so an edge can show the whole
        team before any of it speaks. An adapter with framework-native handoffs lists the agents its
        agent graph names publicly, without building a new graph; one it cannot list early is reported
        in the ``agent_changed`` event that first names it. This default, for an adapter without
        handoffs, is the agent alone. It must not raise: a graph that cannot run is reported by
        :meth:`connect`.

        :param agent: The agent the conversation starts with.
        """
        return [agent.name]

    def initial_speaker(self, agent: "Agent") -> str | None:
        """The agent that speaks first, or ``None`` when only the native session can tell.

        The pool announces it, with :meth:`team`, ahead of any output. This default is the agent
        itself. An adapter whose root does not speak (an ADK workflow container) returns ``None`` and
        reports the first speaking agent in its own ``agent_changed`` event, with the roster.

        :param agent: The agent the conversation starts with.
        """
        return agent.name

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """Not supported for realtime runners."""
        raise NotImplementedError("Realtime runners do not support unary stream().")
        yield

    @abstractmethod
    async def connect(self, session: Session, agent: "Agent", callback: Callable) -> None:
        """
        Opens the framework's native live session for ``agent`` and starts reporting its output.

        The pool relies on these rules:

        - Report native events through ``callback`` **in the order the native session produced
          them**: the pool paces audio and orders ``done`` / ``interrupt`` behind it on that basis.
        - ``callback`` is a coroutine function; await every call.
        - If connecting fails (or is cancelled), close anything already opened before raising.
        - Report a native session that fails while connected as ``error``, but not a close caused by
          :meth:`disconnect`.
        - Reject an agent or option the native live path cannot run with ``TypeError`` / ``ValueError``
          naming the agent and the offending part, before opening anything.

        :param session: The session to bind this connection to.
        :param agent: The agent instance.
        :param callback: The event callback from the pool, awaited as ``callback(event_type, data)``.
            These are the only event names; any other, ``tool_call`` included, fails the connection:

            - ``audio_delta``: ``{"delta": <base64 PCM16 at output_sample_rate>, "message_id": str}``
            - ``transcript_delta``: ``{"delta": <text>, "message_id": str}``
            - ``done``: ``{"status": ...}``, the end of a model turn
            - ``error``: ``{"message": str}``, the native session failed; the pool tells the user and
              replaces the connection
            - ``interrupt``: ``{}``, the user spoke while the model was responding
            - ``speech_started``: ``{}``, the user spoke outside a response; the pool treats it as a
              barge-in only while it still holds audio the user has not heard
            - ``agent_changed``: ``{"agent": str, "previous_agent": str | None, "agents": list[str]
              (optional)}``, the native session moved the turn to another speaking agent; report it
              after the previous agent's last output and before the new agent's first. ``agents``
              carries the roster when this change names an agent the roster did not hold. The pool
              announces :meth:`initial_speaker` (and its :meth:`team`) itself, so an adapter reports
              only the changes, plus the first speaker when :meth:`initial_speaker` is ``None``
        """
        raise NotImplementedError()

    @abstractmethod
    async def append_audio(self, base64_audio: str) -> None:
        """Sends caller audio to the native session, at :attr:`input_sample_rate`."""
        raise NotImplementedError()

    @abstractmethod
    async def send_text(self, text: str) -> None:
        """Sends a caller text message to the native session."""
        raise NotImplementedError()

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Closes the native live session and everything the adapter opened for it.

        Must be safe to call more than once, and after a :meth:`connect` that failed or never ran:
        the pool calls it on idle eviction, on a failed session, when a connect fails or times out,
        and at shutdown.
        """
        raise NotImplementedError()
