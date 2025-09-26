from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Tracer(ABC):
    """
    Abstract base class for tracing providers.

    Concrete implementations should adapt a specific provider SDK (e.g., Traceloop, LangSmith)
    and expose a minimal, common interface used by the Agent Kernel.
    """

    def __init__(self, app_name: str, variables: Optional[Dict[str, Any]] = None) -> None:
        """Create a tracer instance, but defer heavy provider initialization to `init`.

        - app_name: logical application or service name used by the tracing backend.
        - variables: optional provider-specific variables (e.g., base URL, project ID).
        """
        self.app_name = app_name
        self.variables = variables or {}

    @abstractmethod
    def init(self) -> None:
        """Initialize the underlying tracing SDK with the configured app name and variables."""
        pass

    @abstractmethod
    def set_custom_tracing_params(self, params: Dict[str, Any]) -> None:
        """Attach custom attributes/labels/properties to subsequent traces/spans."""
        pass

    def shutdown(self) -> None:
        """shutdown tracer if the provider supports it."""
        return None
