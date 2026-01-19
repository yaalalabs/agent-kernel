from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Agent, Session

from .model import AgentReply, AgentRequest

"""
PreHook and PostHook classes define the interface for hooks that can be executed before and after an agent's execution respectively.
These hooks allow for modification of prompts before execution and replies after execution, enabling functionalities such as context injection, validation, moderation, logging, and analytics. 

Currently, they will get only called for the initial execution of an agent when a user prompt is provided. It's unable to hook into agent-to-agent calls within a workflow. This will be a future enhancement.
"""


class PreHook(ABC):
    @abstractmethod
    async def on_run(self, session: "Session", agent: "Agent", requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        """
        Hook method called before an agent starts executing a prompt. These hooks can modify the prompt or halt execution.
        Some use cases:
          - RAG context injection
          - Prompt validation like input guard rails
          - Logging or analytics

        :param: session (Session): The session instance.
        :param: agent (Agent): The agent that will execute the prompt.
        :param: requests (list[AgentRequest]): The list of requests provided to the agent.
        :return:
                - AgentReply: If the hook decides to halt execution, it can return an AgentReply which will be sent
                - list[AgentRequest]: The modified requests or the input list. You can modify the requests in place without taking copies
                                      You can also add additional content to the requests list. e.g. files, images, etc.

        """
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        """
        Returns the name of the prehook.
        """
        raise NotImplementedError


class PostHook(ABC):
    @abstractmethod
    async def on_run(self, session: "Session", requests: list[AgentRequest], agent: "Agent", agent_reply: AgentReply) -> AgentReply:
        """
        Hook method called after an agent finishes executing a prompt. These hooks can modify the agent's reply. Some use cases:
          - Moderation of agent replies. e.g. output guardrails
          - Adding disclaimers or additional information to the reply
          - Logging or analytics

        Note: if the hook changes the reply, the modified reply will be sent to the next hook for processing.
              The agent_reply parameter contains the unmodified reply from the agent for the first posthook, and the reply modified by previous posthooks for subsequent hooks.

        :param:  session (Session): The session instance.
        :param:  requests (list[AgentRequest]): The original requests provided to the agent after any pre-execution hooks have been applied.
        :param:  agent (Agent): The agent that executed the prompt.
        :param:  agent_reply (AgentReply): The reply to process. For the first posthook, this is the unmodified
                              agent reply. For subsequent posthooks, this is the reply modified by previous posthooks in the chain.

        :return: The modified reply. If not modified, return the current reply.
        """
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        """
        :return: the name of the posthook.
        """
        raise NotImplementedError
