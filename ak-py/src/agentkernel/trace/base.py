from abc import ABC, abstractmethod


class BaseTrace(ABC):
    @abstractmethod
    def init(self):
        """
        Initialize trace instrumentation
        """
        raise NotImplementedError

    @abstractmethod
    def openai(self):
        """
        Initialize OpenAI Agents SDK instrumentation
        """
        raise NotImplementedError
