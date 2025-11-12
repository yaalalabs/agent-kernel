from ..core.config import AKConfig
from .base import BaseTrace


class Trace(BaseTrace):

    def __init__(self):
        self._enabled = AKConfig.get().trace.enabled
        self._type = AKConfig.get().trace.type
        self._instance = None
        if self._enabled:
            if self._type == "langfuse":
                from .langfuse import LangFuse

                self._instance = LangFuse()
            else:
                raise Exception(f"Unknown trace type: {self._type}")
        self.init()

    def init(self):
        if self._enabled:
            self._instance.init()

    def openai(self) -> "Trace":
        if self._enabled:
            self._instance.openai()

        return self
