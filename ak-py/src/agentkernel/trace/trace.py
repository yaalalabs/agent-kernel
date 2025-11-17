from __future__ import annotations

from ..core import Runner
from ..core.config import AKConfig
from .base import BaseTrace


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
        enabled = config.trace.enabled
        trace_type = config.trace.type

        instance = None
        if enabled:
            if trace_type == "langfuse":
                from .langfuse.langfuse import LangFuse

                instance = LangFuse()
            elif trace_type == "openllmetry":
                from .openllmetry.openllmetry import OpenLLMetry

                instance = OpenLLMetry()
            else:
                raise Exception(f"Unknown trace type: {trace_type}")

        trace = cls(instance)
        trace.init()
        return trace

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
