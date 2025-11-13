from abc import ABC, abstractmethod
from typing import Any

from ..core import Session


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


class BaseRunner(ABC):
    @abstractmethod
    async def run(self, agent: Any, session: Session, prompt: Any):
        """
        Runs the agent with the provided prompt.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param prompt: The prompt to provide to the agent.
        :return: The result of the agent's execution.
        """
        raise NotImplementedError
