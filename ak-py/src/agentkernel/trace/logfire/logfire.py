from __future__ import annotations

import logging
import threading

import logfire

from ...core import Runner
from ..base import BaseTrace


class Logfire(BaseTrace):

    _init_lock = threading.Lock()
    _configured = False

    def __init__(self):
        """
        Initializes a Logfire instance.
        """
        self._log = logging.getLogger("ak.trace.logfire")

    def init(self):
        """
        Configures Logfire once. Every framework Module triggers init() via Trace.get(),
        so the configure call is guarded by a class-level lock and flag.
        """
        with Logfire._init_lock:
            if not Logfire._configured:
                logfire.configure(service_name="AgentKernel", send_to_logfire="if-token-present")
                Logfire._configured = True
                self._log.debug("Logfire configured")

    def openai(self) -> Runner:
        """
        Returns the Logfire OpenAI runner instance.
        """
        from .openai import LogfireOpenAIRunner

        return LogfireOpenAIRunner()

    def langgraph(self) -> Runner:
        """
        Returns the Logfire LangGraph runner instance.
        """
        from .langgraph import LogfireLangGraphRunner

        return LogfireLangGraphRunner()

    def crewai(self) -> Runner:
        """
        Returns the Logfire CrewAI runner instance.
        """
        from .crewai import LogfireCrewAIRunner

        return LogfireCrewAIRunner()

    def adk(self) -> Runner:
        """
        Returns the Logfire ADK runner instance.
        """
        from .adk import LogfireADKRunner

        return LogfireADKRunner()

    def smolagents(self) -> Runner:
        """
        Returns the Logfire Smolagents runner instance.
        """
        from .smolagents import LogfireSmolagentsRunner

        return LogfireSmolagentsRunner()

    def pydanticai(self) -> Runner:
        """
        Returns the Logfire Pydantic AI runner instance.
        """
        from .pydanticai import LogfirePydanticAIRunner

        return LogfirePydanticAIRunner()
