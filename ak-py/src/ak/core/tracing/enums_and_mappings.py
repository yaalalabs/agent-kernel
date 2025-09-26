from enum import Enum
from typing import Type

from .tracers import Tracer, TraceloopTracer


class TracingProviderEnum(str, Enum):
    traceloop = "traceloop"


# Mapping from tracing provider enum value (lowercase string) to the tracer class
PROVIDER_TO_TRACER_CLASS: dict[str, Type[Tracer]] = {
    TracingProviderEnum.traceloop.value: TraceloopTracer,
}