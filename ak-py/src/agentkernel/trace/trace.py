from __future__ import annotations

from ..core.config import AKConfig
from .base import BaseRunner, BaseTrace


class Trace(BaseTrace):

    def __init__(self):
        """
        Initializes a Trace instance.
        """
        self._enabled = AKConfig.get().trace.enabled
        self._type = AKConfig.get().trace.type
        self._instance = None
        if self._enabled:
            if self._type == "langfuse":
                from .langfuse.langfuse import LangFuse

                self._instance = LangFuse()
            else:
                raise Exception(f"Unknown trace type: {self._type}")
        self.init()

    def init(self):
        """
        Initializes the trace instance.
        """
        if self._enabled:
            self._instance.init()

    def openai(self) -> BaseRunner | None:
        """
        Returns the OpenAI trace runner instance.
        """
        if self._enabled:
            return self._instance.openai()
        return None
