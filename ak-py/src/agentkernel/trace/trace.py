from __future__ import annotations

from ..core import Runner
from ..core.config import AKConfig
from ..core.util.factory import AKConfigError, require_extra, resolve_dotted
from .base import BaseTrace

_BUILTIN_TRACERS = ["langfuse", "openllmetry"]


class Trace(BaseTrace):
    """
    Factory class for creating trace instances based on configuration.
    """

    def __init__(self, instance: BaseTrace | None = None):
        """
        Initializes a Trace instance with a specific trace implementation.

        :param instance: The trace implementation instance (e.g., LangFuse).
        """
        self._instance = instance

    @classmethod
    def get(cls) -> "Trace":
        """
        Factory method to create a Trace instance based on configuration.

        :return: A Trace instance with the appropriate trace implementation.
        """
        config = AKConfig.get()
        instance = cls._build(config.trace.type) if config.trace.enabled else None
        trace = cls(instance)
        trace.init()
        return trace

    @staticmethod
    def _build(trace_type: str) -> BaseTrace:
        """Resolve the configured tracer: a built-in short name, or a dotted path to a
        user-supplied ``BaseTrace`` subclass (bring-your-own)."""
        if trace_type == "langfuse":
            with require_extra("langfuse", "trace.type: langfuse"):
                from .langfuse.langfuse import LangFuse

            return LangFuse()
        if trace_type == "openllmetry":
            with require_extra("openllmetry", "trace.type: openllmetry"):
                from .openllmetry.openllmetry import OpenLLMetry

            return OpenLLMetry()
        if "." not in trace_type:
            raise AKConfigError(f"unknown trace type '{trace_type}'; expected one of {_BUILTIN_TRACERS} or a dotted path to a BaseTrace subclass")
        return resolve_dotted(trace_type, base=BaseTrace)()

    def init(self):
        """
        Initializes the trace instance.
        """
        if self._instance is not None:
            self._instance.init()

    def openai(self) -> Runner | None:
        """
        Returns the OpenAI trace runner instance.
        """
        if self._instance is not None:
            return self._instance.openai()
        return None

    def langgraph(self) -> Runner | None:
        """
        Returns the LangGraph trace runner instance.
        """
        if self._instance is not None:
            return self._instance.langgraph()
        return None

    def crewai(self) -> Runner | None:
        """
        Returns the CrewAI trace runner instance.
        """
        if self._instance is not None:
            return self._instance.crewai()
        return None

    def adk(self) -> Runner | None:
        """
        Returns the ADK trace runner instance.
        """
        if self._instance is not None:
            return self._instance.adk()
        return None

    def smolagents(self) -> Runner | None:
        """
        Returns the Smolagents trace runner instance.
        """
        if self._instance is not None:
            return self._instance.smolagents()
        return None
