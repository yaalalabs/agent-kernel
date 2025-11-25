from abc import ABC, abstractmethod
from typing import Any

from .base import Agent, Session

"""
Prehook and Posthook classes define the interface for hooks that can be executed before and after an agent's execution respectively.
These hooks allow for modification of prompts before execution and replies after execution, enabling functionalities such as context injection, validation, moderation, logging, and analytics. 

Currently, they will get only called for the initial execution of an agent when a user prompt is provided. It's unable to hook into agent-to-agent calls within a workflow. This will be a future enhancement.
"""


class Prehook(ABC):
    @abstractmethod
    async def on_run(
        self, session: Session, agent: Agent, original_prompt: str, prompt: str, additional_context: Any | None
    ) -> tuple[bool, str]:
        """
        Hook method called before an agent starts executing a prompt. These hooks can modify the prompt or halt execution.
        Some use cases:
          - RAG context injection
          - Prompt validation like input guard rails
          - Logging or analytics

        :param: session (Session): The session instance.
        :param: agent (Agent): The agent that will execute the prompt.
        :param: original_prompt (str): The original unmodified prompt provided to the agent.
        :param: prompt (str): The current prompt to be executed.
        :param: additional_context (Any|None): Additional context that may have been passed with the prompt. This may help RAG hooks to fetch relevant context.
        :return: tuple[bool, str]: A tuple containing:
                - bool: Whether to proceed with execution.
                - str: The modified prompt. In case of stopping execution, a clear reason to be sent back
                       to the user. Otherwise, a modified prompt (e.g. RAG context)
                       can be sent for further processing.
        """
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        """
        Returns the name of the prehook.
        """
        raise NotImplementedError


class Posthook(ABC):
    @abstractmethod
    async def on_run(self, session: Session, input_prompt: str, additional_context: Any | None, agent: Agent, agent_reply: str) -> str:
        """
        Hook method called after an agent finishes executing a prompt. These hooks can modify the agent's reply. Some use cases:
          - Moderation of agent replies. e.g. output guardrails
          - Adding disclaimers or additional information to the reply
          - Logging or analytics

        Note: if the hook changes the reply, the modified reply will be sent to the next hook for processing.
              the agent_reply parameter contains the unmodified reply from the agent. the following code snippet will help to correctly handle the response

              if hasattr(result, "raw"):
                response_text = str(result.raw)
              else:
                response_text = str(result)

        :param:  session (Session): The session instance.
        :param:  input_prompt (str): The original prompt provided to the agent after any pre-execution hooks have been applied.
        :param: additional_context (Any|None): Additional context that may have been passed with the prompt.
        :param:  agent (Agent): The agent that executed the prompt.
        :param:  agent_reply (str): The reply to process. For the first posthook, this is the unmodified
                              agent reply. For subsequent posthooks, this is the reply modified by
                              previous posthooks in the chain.

        :return: The modified reply. If not modified, return the current reply.
        """
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        """
        :return: the name of the posthook.
        """
        raise NotImplementedError
