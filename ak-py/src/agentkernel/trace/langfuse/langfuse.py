from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from langfuse import Langfuse, get_client, propagate_attributes

from ... import Runner
from ...core.realtime import RealtimeRunner
from ..base import BaseTrace, RealtimeCallSpan
from ..fetch import FetchedSpan, TraceQuery


class LangFuseRealtimeCallSpan(RealtimeCallSpan):
    """
    A realtime call's span through Langfuse's own client. Not a plain OpenTelemetry span: Langfuse's default export filter
    drops a span that has no ``gen_ai.*`` attribute and does not come from its own tracer.
    """

    def __init__(self, client: Langfuse, name: str, session_id: str):
        """
        :param client: The Langfuse client.
        :param name: The observation name.
        :param session_id: The session the call belongs to, as the provider's ``run()`` span tags it.
        """
        self._client = client
        self._name = name
        self._session_id = session_id
        self._observation = None
        self._ended = False

    @contextmanager
    def opened(self) -> Iterator[None]:
        with propagate_attributes(session_id=self._session_id, tags=["agentkernel"]):
            # end_on_exit=False: the observation outlives this block and is ended by end(), from another task.
            with self._client.start_as_current_observation(name=self._name, as_type="span", end_on_exit=False) as observation:
                self._observation = observation
                yield

    def fail(self, message: str) -> None:
        if self._observation is not None and not self._ended:
            self._observation.update(level="ERROR", status_message=message)

    def end(self) -> None:
        if self._observation is not None and not self._ended:
            self._ended = True
            self._observation.end()


class LangFuse(BaseTrace):

    def __init__(self):
        """
        Initializes a LangFuse instance.
        """
        self._client: Langfuse | None = None
        self._log = logging.getLogger("ak.trace.langfuse")

    @staticmethod
    def flush_on_lambda(client: Langfuse) -> None:
        """
        Exports the spans the Langfuse client still holds when running on AWS Lambda. Lambda freezes the
        sandbox as soon as an invocation returns, so the client's background exporter would otherwise hold
        the spans until the next invocation, or lose them when the sandbox is recycled. A failed flush is
        logged, never raised, so tracing can't fail the agent's reply.
        :param client: The Langfuse client the runner sent its spans with.
        """
        if "AWS_LAMBDA_FUNCTION_NAME" not in os.environ:
            return
        try:
            client.flush()
        except Exception:  # any exporter error: the reply must still be returned
            logging.getLogger("ak.trace.langfuse").warning("Flushing Langfuse spans after the run failed", exc_info=True)

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

    def smolagents(self) -> Runner:
        """
        Returns the Langfuse Smolagents runner instance.
        """
        from .smolagents import LangFuseSmolagentsRunner

        return LangFuseSmolagentsRunner(self._client)

    def pydanticai(self) -> Runner:
        """
        Returns the Langfuse Pydantic AI runner instance.
        """
        from .pydanticai import LangFusePydanticAIRunner

        return LangFusePydanticAIRunner(self._client)

    def maf(self) -> Runner:
        """
        Returns the Langfuse MAF runner instance.
        """
        from .maf import LangFuseMAFRunner

        return LangFuseMAFRunner(self._client)

    def claude(self) -> Runner:
        """
        Returns the Langfuse Claude Agent SDK runner instance.
        """
        from .claude import LangFuseClaudeRunner

        return LangFuseClaudeRunner(self._client)

    def openai_realtime(self) -> type[RealtimeRunner]:
        """
        Returns the Langfuse OpenAI realtime runner class.
        """
        from .openai import LangFuseOpenAIRealtimeRunner

        return LangFuseOpenAIRealtimeRunner

    def adk_realtime(self) -> type[RealtimeRunner]:
        """
        Returns the Langfuse ADK realtime runner class.
        """
        from .adk import LangFuseADKRealtimeRunner

        return LangFuseADKRealtimeRunner

    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]:
        """
        Fetches observations back from Langfuse with the same client used for sending.
        """
        from .fetch import LangfuseTraceFetcher

        return LangfuseTraceFetcher(self._client).fetch_spans(query)
