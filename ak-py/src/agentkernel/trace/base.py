from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, ClassVar

from ..core import Agent, Runner, Session
from ..core.realtime import RealtimeRunner
from .fetch import FetchedSpan, TraceQuery


class RealtimeCallSpan(ABC):
    """
    One trace span over a realtime call: opened around ``connect``, ended at ``disconnect``.

    A call's span outlives the task that opens it, which is why it is not a single ``with`` block as a
    ``Runner.run`` span is. Implementations hold their provider's span object.
    """

    @abstractmethod
    def opened(self) -> AbstractContextManager[None]:
        """
        Starts the span and makes it current, with the provider's session tagging, for the block. Entered once,
        around ``connect``: tasks started inside inherit it. The span stays open after the block.
        """
        raise NotImplementedError

    @abstractmethod
    def fail(self, message: str) -> None:
        """
        Marks the span as failed.
        :param message: What failed.
        """
        raise NotImplementedError

    @abstractmethod
    def end(self) -> None:
        """
        Ends the span. Safe to call twice, and when ``opened()`` was never entered or raised.
        """
        raise NotImplementedError


class TracedRealtimeRunner(RealtimeRunner):
    """
    Base of every traced realtime runner: one :class:`RealtimeCallSpan` per call, opened when ``connect`` starts and
    ended in ``disconnect``. List it before the framework's realtime runner in the bases, so the framework runner is
    the ``super()``: ``class X(TracedRealtimeRunner, OpenAIRealtimeRunner)``.

    The span covers the native session, not the pool's hooks, as a ``run()`` span covers ``runner.run`` and not the
    post-hooks.
    """

    SPAN_NAME: ClassVar[str]

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._call_span: RealtimeCallSpan | None = None
        self._connecting = False

    @abstractmethod
    def _start_call_span(self, session: Session, agent: Agent) -> RealtimeCallSpan:
        """
        Builds this call's span (not started yet).
        :param session: The session the call belongs to, tagged on the span as the provider's ``run()`` span does.
        :param agent: The agent the call starts with.
        """
        raise NotImplementedError

    async def connect(self, session: Session, agent: Agent, callback: Callable) -> None:
        span = self._start_call_span(session, agent)
        self._call_span = span
        self._connecting = True
        try:
            with span.opened():
                await super().connect(session, agent, self._watched(callback))
        except BaseException as error:  # cancellation included: the adapters close what they opened before raising
            span.fail(repr(error))
            span.end()
            self._call_span = None
            raise
        finally:
            self._connecting = False

    def _watched(self, callback: Callable) -> Callable:
        """
        Wraps the pool's callback so an ``error`` event marks the span as failed; every event reaches the callback unchanged.
        """

        async def watched(event_type: str, data: dict) -> None:
            span = self._call_span
            if event_type == "error" and span is not None:
                span.fail(data.get("message") or "realtime session error")
            await callback(event_type, data)

        return watched

    async def disconnect(self) -> None:
        try:
            await super().disconnect()
        finally:
            # An adapter closes itself when its connect fails; that connect, not this call, ends the span after marking it failed.
            if not self._connecting:
                span, self._call_span = self._call_span, None
                if span is not None:
                    span.end()


class BaseTrace(ABC):
    @abstractmethod
    def init(self):
        """
        Initialize trace instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def openai(self) -> Runner:
        """
        Initialize OpenAI Agents SDK instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def langgraph(self) -> Runner:
        """
        Initialize LangGraph instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def crewai(self) -> Runner:
        """
        Initialize CrewAI instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def adk(self) -> Runner:
        """
        Initialize Google ADK instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def smolagents(self) -> Runner:
        """
        Initialize Smolagents instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def pydanticai(self) -> Runner:
        """
        Initialize Pydantic AI instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def maf(self) -> Runner:
        """
        Initialize Microsoft Agent Framework instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def claude(self) -> Runner:
        """
        Initialize Claude Agent SDK instrumentation.
        """
        raise NotImplementedError

    def openai_realtime(self) -> type[RealtimeRunner] | None:
        """
        The traced realtime runner class for OpenAI Agents SDK agents, built with no arguments once per call.

        Not abstract, so bring-your-own tracers keep working: by default nothing is traced and the untraced runner is used.
        """
        return None

    def adk_realtime(self) -> type[RealtimeRunner] | None:
        """
        The traced realtime runner class for Google ADK agents. See :meth:`openai_realtime`.
        """
        return None

    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]:
        """
        Fetch spans back from the tracing provider's cloud, oldest first.

        Not abstract, so bring-your-own tracers that only send traces keep working.

        :param query: The provider-neutral filter (time window, span kinds, session, ...).
        """
        raise NotImplementedError(f"{type(self).__name__} does not support fetching spans")
