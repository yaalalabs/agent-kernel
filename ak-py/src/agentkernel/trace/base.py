from abc import ABC, abstractmethod

from ..core import Runner
from .fetch import FetchedSpan, TraceQuery


class BaseTrace(ABC):
    @abstractmethod
    def init(self):
        """
        Initialize trace instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def openai(self) -> Runner:
        """
        Initialize OpenAI Agents SDK instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def langgraph(self) -> Runner:
        """
        Initialize LangGraph instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def crewai(self) -> Runner:
        """
        Initialize CrewAI instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def adk(self) -> Runner:
        """
        Initialize Google ADK instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def smolagents(self) -> Runner:
        """
        Initialize Smolagents instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def pydanticai(self) -> Runner:
        """
        Initialize Pydantic AI instrumentation
        """
        raise NotImplementedError

    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        """
        Fetch spans back from the tracing provider's cloud, oldest first.

        Not abstract, so bring-your-own tracers that only send traces keep working.

        :param query: The provider-neutral filter (time window, span kinds, session, ...).
        """
        raise NotImplementedError(f"{type(self).__name__} does not support fetching traces")
