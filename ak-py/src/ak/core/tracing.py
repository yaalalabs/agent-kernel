from typing import Optional
import logging
from traceloop.sdk import Traceloop
from .config import AKConfig

class TraceloopTracing:
    # Define a class-level logger rather than a module-level one
    _log = logging.getLogger("TraceloopTracing")
    def __init__(self, app_name: str = "ak-py"):
        Traceloop.init(app_name=app_name)

    def set_custom_tracing_params(self, params: dict) -> None:
        """Attach custom association properties (e.g., thread_id, metadata)."""
        Traceloop.set_association_properties(params)

    @classmethod
    def get_tracer(cls, name: Optional[str] = "ak-tracer") -> Optional["TraceloopTracing"]:
        """Create a TraceloopTracing instance using global tracing configuration.

        Args:
            name: Optional override for the tracer app name.

        Returns:
            TraceloopTracing instance, or None if tracing is not enabled.
        """
        tracing_enabled = bool(AKConfig.get().tracing)

        cls._log.debug(f"TraceloopTracing.get_tracer called (enabled={tracing_enabled}, name={name})")

        if not tracing_enabled:
            cls._log.debug("Tracing not enabled; returning None")
            return None

        app_name = name

        cls._log.debug(f"Creating TraceloopTracing with app_name '{app_name}'")
        return cls(app_name=app_name)
