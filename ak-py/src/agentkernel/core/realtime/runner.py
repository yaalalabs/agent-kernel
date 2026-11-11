from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable
from typing import Any

from ..base import Agent, Runner, Session
from ..event import StreamEvent
from ..model import AgentReply, AgentRequest
from .pcm import EDGE_SAMPLE_RATE


class RealtimeRunner(Runner):
    """Base class for adapters that run a live conversation on the framework's own realtime runner.

    The framework owns the conversation (speaker, tools, handoffs); the adapter feeds it caller input and
    reports its output through the ``callback`` given to :meth:`connect`. One instance per connection.
    ``framework_context`` is neither injected nor stored. Bring your own via ``realtime_runner_cls`` on the ``Module``.
    """

    input_sample_rate: int = EDGE_SAMPLE_RATE
    output_sample_rate: int = EDGE_SAMPLE_RATE

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
        raise NotImplementedError("Realtime runners do not support unary stream().")
        yield

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
        :param callback: Awaited as ``callback(event_type, data)``; any other event name fails the connection:

            - ``audio_delta``: ``{"delta": <base64 PCM16 at output_sample_rate>, "message_id": str}``
            - ``transcript_delta``: ``{"delta": str, "message_id": str}``
            - ``done``: ``{"status": ...}``, the end of a model turn
            - ``error``: ``{"message": str}``, the native session failed
            - ``interrupt``: ``{}``, the user spoke while the model was responding
            - ``speech_started``: ``{}``, the user spoke outside a response
            - ``agent_changed``: ``{"agent": str, "previous_agent": str | None, "agents": list[str] (optional)}``,
              between the old agent's last output and the new one's first; ``agents`` when the roster grew
            - ``input_transcript``: ``{"text": str, "message_id": str}``, one finished, non-empty caller utterance
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
