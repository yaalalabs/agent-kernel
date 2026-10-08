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

    The realtime pool creates one instance per session connection, so an instance may keep that
    connection's socket and state on ``self``. The pool owns everything around the model socket
    (audio pacing, barge-in decisions, tool execution scopes, queue emission); an adapter only
    talks to the model and reports what it does through the ``callback`` given to :meth:`connect`,
    which is why an adapter never imports pipeline types.

    Bring your own adapter by passing its class as ``realtime_runner_cls`` to the framework's
    ``Module``.
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

        The pool relies on these rules:

        - Report model events through ``callback`` **in the order the model sent them**: the pool
          paces audio and orders ``done`` / ``interrupt`` behind it on that basis.
        - ``callback`` is a coroutine function; await every call.
        - If connecting fails, close anything already opened before raising: the pool drops a
          connection that failed to connect without calling :meth:`disconnect`.
        - Report a socket that fails while connected as ``error``, but not a close caused by
          :meth:`disconnect`.

        :param session: The session to bind this connection to.
        :param agent: The agent instance.
        :param callback: The event callback from the pool, awaited as ``callback(event_type, data)``:

            - ``audio_delta``: ``{"delta": <base64 PCM16 at output_sample_rate>, "message_id": str}``
            - ``transcript_delta``: ``{"delta": <text>, "message_id": str}``
            - ``tool_call``: ``{"call_id": str, "name": str, "arguments": <JSON string>}``; the pool
              then calls :meth:`execute_tool` and :meth:`send_tool_result`
            - ``done``: ``{"status": ...}``, the end of a model turn
            - ``error``: ``{"message": str}``, the socket failed; the pool tells the user and
              replaces the connection
            - ``interrupt``: ``{}``, the user spoke while the model was responding
            - ``speech_started``: ``{}``, the user spoke outside a response; the pool treats it as a
              barge-in only while it still holds audio the user has not heard
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

        Must be safe to call more than once, and after a :meth:`connect` that failed or never ran:
        the pool calls it on idle eviction, on a failed socket, and at shutdown.
        """
        raise NotImplementedError()
