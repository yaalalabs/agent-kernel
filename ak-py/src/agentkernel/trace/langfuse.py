import logging

from langfuse import get_client

from .base import BaseTrace


class LangFuse(BaseTrace):
    def __init__(self):
        self._client = None
        self._log = logging.getLogger("ak.trace.langfuse")

    def init(self):
        self._client = get_client()
        if self._client.auth_check():
            self._log.debug("Langfuse client is authenticated and ready!")
        else:
            raise Exception("Langfuse client is not authenticated!")

    def openai(self):
        self._log.debug("Instrumenting OpenAI agents")
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

        OpenAIAgentsInstrumentor().instrument()
