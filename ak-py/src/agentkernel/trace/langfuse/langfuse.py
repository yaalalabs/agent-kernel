from __future__ import annotations

import logging

from langfuse import Langfuse, get_client

from ... import Runner
from ..base import BaseTrace


class LangFuse(BaseTrace):

    def __init__(self):
        """
        Initializes a LangFuse instance.
        """
        self._client: Langfuse | None = None
        self._log = logging.getLogger("ak.trace.langfuse")

    def init(self):
        """
        Initializes the Langfuse client.
        """
        self._client = get_client()
        if self._client.auth_check():
            self._log.debug("Langfuse client is authenticated and ready!")
        else:
            raise Exception("Langfuse client is not authenticated!")

    def openai(self):
        """
        Returns the Langfuse OpenAI runner instance.
        """
        from .openai import LangFuseOpenAIRunner

        return LangFuseOpenAIRunner(self._client)

    def langgraph(self):
        """
        Returns the Langfuse LangGraph runner instance.
        """
        from .langgraph import LangFuseLangGraph

        return LangFuseLangGraph(self._client)

    def crewai(self) -> Runner:
        """
        Returns the Langfuse CrewAI runner instance.
        """
        from .crewai import LangFuseCrewAIRunner

        return LangFuseCrewAIRunner(self._client)

    def adk(self) -> Runner:
        """
        Returns the Langfuse ADK runner instance.
        """
        from .adk import LangFuseADKRunner

        return LangFuseADKRunner(self._client)
