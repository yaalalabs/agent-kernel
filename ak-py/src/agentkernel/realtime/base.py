from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable
from enum import StrEnum
from typing import Any

from ..core.base import Agent, Runner, Session
from ..core.event import StreamEvent
from ..core.model import AgentReply, AgentRequest
from .audio import EDGE_SAMPLE_RATE


class RealtimeRunner(Runner):
    """Base class for adapters that run a live conversation on the framework's own realtime runner.

    The framework owns the conversation (speaker, tools, handoffs); the adapter feeds it caller input and
    reports its output through the ``callback`` given to :meth:`connect`. One instance per connection.
    ``framework_context`` is neither injected nor stored. Bring your own via ``realtime_runner_cls`` on the ``Module``.
    """

    class Event(StrEnum):
        """The event names a runner reports through the ``callback`` given to :meth:`connect`.

        A member is a ``str`` equal to its value, so a custom runner may keep passing plain strings
        (``callback("audio_delta", ...)``); the pool compares by value and treats both the same.
        """

        AUDIO_DELTA = "audio_delta"
        TRANSCRIPT_DELTA = "transcript_delta"
        DONE = "done"
        ERROR = "error"
        INTERRUPT = "interrupt"
        SPEECH_STARTED = "speech_started"
        AGENT_CHANGED = "agent_changed"
        INPUT_TRANSCRIPT = "input_transcript"

    input_sample_rate: int = EDGE_SAMPLE_RATE
    output_sample_rate: int = EDGE_SAMPLE_RATE

    # The default for a custom runner; the framework adapters set their own in ``__init__`` (``ak.<framework>.realtime``).
    _log: logging.Logger = logging.getLogger("ak.realtime.runner")

    def __init__(self, name: str):
        """
        :param name: The framework's runner name.
        """
        super().__init__(name)
        # The pool's callback, given to ``connect()``.
        self._callback: Callable | None = None
        # Set by ``disconnect()``: the native session ending after that is expected, not a failure.
        self._closing = False
        # The agent speaking now, and every agent that has spoken or was announced: see ``_speaker_changed``.
        self._speaker: str | None = None
        self._roster: list[str] = []

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """Not supported for realtime runners."""
        raise NotImplementedError("Realtime runners do not support unary run().")

    @staticmethod
    async def _cancel_and_wait(task: asyncio.Task | None) -> None:
        """Cancel ``task`` and wait for it to end; a no-op for ``None`` or the calling task itself."""
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.wait({task})

    def team(self, agent: "Agent") -> list[str]:
        """The speaking agents a conversation with ``agent`` can reach, announced before connecting. Must not raise.

        :param agent: The agent the conversation starts with.
        :return: The agent names, ``agent`` first.
        """
        return [agent.name]

    def initial_speaker(self, agent: "Agent") -> str | None:
        """The agent that speaks first, or ``None`` when the adapter reports it in its first ``agent_changed``.

        :param agent: The agent the conversation starts with.
        """
        return agent.name

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """Not supported for realtime runners."""
        raise NotImplementedError("Realtime runners do not support stream(): a realtime call is driven through connect().")
        yield

    # -- shared by the framework adapters ------------------------------------------------------------------

    async def _speaker_changed(self, agent: str, previous: str | None = None) -> None:
        """Report a change of speaker once, with the roster when the agent is new to it. Not an override point.

        A framework may name the speaker on several events (OpenAI on both handoff and agent_start); only the first reports.

        :param agent: The agent that speaks now.
        :param previous: The agent that spoke before, when the framework says so; defaults to the last reported speaker.
        """
        if agent == self._speaker:
            return
        data: dict[str, Any] = {"agent": agent, "previous_agent": previous or self._speaker}
        if agent not in self._roster:
            self._roster.append(agent)
            data["agents"] = list(self._roster)
        self._speaker = agent
        await self._callback(RealtimeRunner.Event.AGENT_CHANGED, data)

    async def _report_listen_failed(self, message: str) -> None:
        """Log that the native event stream raised and, unless :meth:`disconnect` caused it, fail the connection. Not an override point.

        Called from the ``except`` of an adapter's ``_listen``, so the log carries the traceback.

        :param message: The error text, for the log and for the ``error`` event.
        """
        self._log.exception(message)
        if not self._closing:
            await self._callback(RealtimeRunner.Event.ERROR, {"message": message})

    async def _report_listen_ended(self, message: str) -> None:
        """Fail the connection because the native event stream ended cleanly, which means the session closed. Not an override point.

        Does nothing after :meth:`disconnect`, where the end is expected.

        :param message: The error text for the ``error`` event.
        """
        if not self._closing:
            await self._callback(RealtimeRunner.Event.ERROR, {"message": message})

    @abstractmethod
    async def connect(self, session: Session, agent: "Agent", callback: Callable) -> None:
        """
        Opens the native live session for ``agent`` and starts reporting its output.

        Rules the pool relies on:

        - Report events in the order the native session produced them; await every ``callback`` call.
        - On a failed or cancelled connect, close what was opened before raising.
        - Report a failure while connected as ``error``, but not a close caused by :meth:`disconnect`.
        - Reject an agent or option the live path cannot run with ``TypeError``/``ValueError`` before opening anything.

        :param session: The session to bind this connection to.
        :param agent: The agent instance.
        :param callback: Awaited as ``callback(event_type, data)`` with an :class:`Event` member (or its string value);
            any other event name fails the connection:

            - ``audio_delta``: ``{"delta": <base64 PCM16 at output_sample_rate>, "message_id": str}``
            - ``transcript_delta``: ``{"delta": str, "message_id": str}``
            - ``done``: ``{"status": ...}``, the end of a model turn
            - ``error``: ``{"message": str}``, the native session failed
            - ``interrupt``: ``{}``, the user spoke while the model was responding
            - ``speech_started``: ``{}``, the user spoke outside a response
            - ``agent_changed``: ``{"agent": str, "previous_agent": str | None, "agents": list[str] (optional)}``,
              between the old agent's last output and the new one's first; ``agents`` when the roster grew
            - ``input_transcript``: ``{"text": str, "message_id": str}``, one finished, non-empty caller utterance, reported
              when the framework completes it (which may be after the response that follows it)
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
        """Closes the native live session; safe to call twice or after a failed or missing :meth:`connect`."""
        raise NotImplementedError()
