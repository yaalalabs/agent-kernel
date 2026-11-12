from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from .base import RealtimeCallSpan


class OTelRealtimeCallSpan(RealtimeCallSpan):
    """
    A realtime call's span as a plain OpenTelemetry span, for the providers whose backend exports every span of the
    tracer provider they install (Logfire, OpenLLMetry, CloudWatch). A subclass adds its provider's session tagging by
    overriding :meth:`_tagged`.

    Imported only by those provider packages: ``opentelemetry`` is not a core dependency, and each of their extras brings it.
    """

    def __init__(self, tracer: Tracer, name: str, attributes: Mapping[str, str]):
        """
        :param tracer: The tracer the span is started on.
        :param name: The span name.
        :param attributes: The attributes set when the span starts, such as the session id.
        """
        self._tracer = tracer
        self._name = name
        self._attributes = dict(attributes)
        self._span: Span | None = None
        self._ended = False

    def _tagged(self) -> AbstractContextManager[None]:
        """
        The provider's session tagging, active while the span starts and for the block, so spans started in the block inherit it.
        """
        return nullcontext()

    @contextmanager
    def opened(self) -> Iterator[None]:
        with self._tagged():
            self._span = self._tracer.start_span(self._name, attributes=self._attributes)
            # end_on_exit=False: the span outlives this block and is ended by end(), from another task.
            with trace.use_span(self._span, end_on_exit=False):
                yield

    def fail(self, message: str) -> None:
        if self._span is not None and not self._ended:
            self._span.set_status(Status(StatusCode.ERROR, message))

    def end(self) -> None:
        if self._span is not None and not self._ended:
            self._ended = True
            self._span.end()
