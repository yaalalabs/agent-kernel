from abc import ABC, abstractmethod

from ..core import Runner


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
