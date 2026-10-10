from __future__ import annotations

import logging
import threading

import logfire

from ...core import Runner
from ..base import BaseTrace
from ..fetch import FetchedSpan, TraceQuery


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
                logfire.configure(
                    service_name="AgentKernel",
                    send_to_logfire="if-token-present",
                    scrubbing=logfire.ScrubbingOptions(callback=Logfire._keep_session_id),
                )
                Logfire._configured = True
                self._log.debug("Logfire configured")

    @staticmethod
    def _keep_session_id(match):
        """
        Logfire's default scrubber redacts anything matching "session", which would erase the AK
        session id on the wrapper span and make traces unfilterable by session.
        """
        if match.path == ("attributes", "session_id"):
            return match.value
        return None

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

    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        """
        Fetches spans back from Logfire through the SQL Query API (needs ``LOGFIRE_READ_TOKEN``).
        """
        from .fetch import LogfireTraceFetcher

        return LogfireTraceFetcher().fetch(query)
