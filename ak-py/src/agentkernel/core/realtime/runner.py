from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Callable

from ..base import Agent, Runner, Session
from ..event import StreamEvent
from ..model import AgentReply, AgentRequest
from .pcm import EDGE_SAMPLE_RATE

if TYPE_CHECKING:  # typing only; ..tool imports ..base, so this avoids a cycle
    from ..tool import ToolContext


class RealtimeRunner(Runner):
    """Base class for framework adapters handling realtime streaming via persistent
    WebSocket/WebRTC connections (e.g. OpenAI Realtime API).

    ``input_sample_rate`` and ``output_sample_rate`` are the PCM16 mono rates the model wants. The
    pipeline converts between these and :data:`~agentkernel.core.realtime.pcm.EDGE_SAMPLE_RATE`, so
    an adapter never resamples and no adapter hardcodes the edge's rate.
    """

    input_sample_rate: int = EDGE_SAMPLE_RATE
    output_sample_rate: int = EDGE_SAMPLE_RATE

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """Not supported for realtime runners."""
        raise NotImplementedError("Realtime runners do not support unary run().")

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """Not supported for realtime runners."""
        raise NotImplementedError("Realtime runners do not support unary stream().")
        yield

    @abstractmethod
    async def connect(self, session: Session, agent: "Agent", callback: Callable) -> None:
        """
        Establishes a persistent socket connection to the framework's Realtime API backend.
        :param session: The session to bind this connection to.
        :param agent: The agent instance.
        :param callback: The event callback from the pool, called as ``callback(event_type, data)``
            with ``audio_delta``, ``transcript_delta``, ``tool_call``, ``done``, ``error``,
            ``interrupt`` (the user spoke while the model was responding) or ``speech_started``
            (the user spoke outside a response; the pool treats it as a barge-in only while it
            still holds audio the user has not heard).
        """
        raise NotImplementedError()

    @abstractmethod
    async def append_audio(self, base64_audio: str) -> None:
        """Appends audio to the model's input buffer, at :attr:`input_sample_rate`."""
        raise NotImplementedError()

    @abstractmethod
    async def send_text(self, text: str) -> None:
        """Sends a text message and requests a response."""
        raise NotImplementedError()

    @abstractmethod
    async def send_tool_result(self, call_id: str, result: str) -> None:
        """Sends a tool execution result back to the model."""
        raise NotImplementedError()

    @abstractmethod
    async def execute_tool(self, name: str, arguments: str, context: "ToolContext", call_id: str) -> str:
        """Executes the named tool with JSON ``arguments`` and returns its string result.

        Owned by the adapter because both the tool object and the context it needs are
        framework-native: the OpenAI SDK expects its own ``ToolContext`` built around the run
        context, and ADK injects a ``ToolContext`` (session state, actions) into tools that
        declare one. The adapter activates ``context`` the way its framework expects; the
        caller only constructs it.

        :param name: Tool name, matching the model's function call.
        :param arguments: Raw JSON argument string the model emitted.
        :param context: The Agent Kernel tool context for this call.
        :param call_id: The model's function-call id (frameworks correlate the response by it).
        :return: The tool result as a string.
        """
        raise NotImplementedError()

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Closes the active persistent socket connection.
        """
        raise NotImplementedError()
