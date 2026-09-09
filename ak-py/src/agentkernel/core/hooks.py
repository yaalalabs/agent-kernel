from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Agent, Session

from .event import StreamEvent
from .model import AgentReply, AgentRequest

"""
PreHook and PostHook classes define the interface for hooks that can be executed before and after an agent's execution respectively.
These hooks allow for modification of prompts before execution and replies after execution, enabling functionalities such as context injection, validation, moderation, logging, and analytics. 

Currently, they will get only called for the initial execution of an agent when a user prompt is provided. It's unable to hook into agent-to-agent calls within a workflow. This will be a future enhancement.
"""


class StreamHalt(Exception):
    """
    Raised by a post-hook to end a streamed run early.

    Runtime.stream catches it, emits the closing event for any boundary the stream left open, and
    yields one terminal StreamChunk carrying `reason` as its error. The session is not stored, so a
    halted turn leaves no trace in conversation state.

    The partial response is invalid rather than merely truncated: a client must discard what it has
    already rendered instead of presenting it as a short answer.
    """

    def __init__(self, reason: str):
        """
        :param reason: Why the run was halted. Reaches the client verbatim as StreamChunk.error.
        """
        super().__init__(reason)
        self.reason = reason


class PreHook(ABC):
    @abstractmethod
    async def on_run(self, session: "Session", agent: "Agent", requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        """
        Hook method called before an agent starts executing a prompt. These hooks can modify the prompt or halt execution.
        Some use cases:
          - RAG context injection
          - Prompt validation like input guardrails
          - Logging or analytics

        :param: session (Session): The session instance.
        :param: agent (Agent): The agent that will execute the prompt.
        :param: requests (list[AgentRequest]): The list of requests provided to the agent.
        :return:
                - AgentReply: If the hook decides to halt execution, it can return an AgentReply which will be sent.
                              This may be an AgentReplyAny carrying structured (dict) content.
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
                              When the agent produces structured output, this is an AgentReplyAny whose `content` holds the
                              structured result as a dict — hooks can inspect and modify the dict directly (not a stringified reply).

        :return: The modified reply. If not modified, return the current reply.
        """
        raise NotImplementedError

    async def on_stream_event(
        self,
        session: "Session",
        requests: list[AgentRequest],
        agent: "Agent",
        event: StreamEvent,
    ) -> StreamEvent | list[StreamEvent] | None:
        """
        Hook method called for every event a streamed run produces, before it reaches the client.

        Unlike on_run, this sees the whole stream: message and reasoning text, tool call names,
        arguments and results, and the boundaries that pair them.

        Returning a list emits several events in place of one, which is what makes hold-and-release
        possible: return None per fragment while accumulating in the session's volatile cache, then
        return [rewritten_payload, closing_event] at the boundary. Accumulate there, not on `self` —
        one hook instance serves every concurrent request. A returned list is emitted as-is and ends
        the chain for that event, so `return event` and `return [event]` are not equivalent.

        :param: session (Session): The session instance.
        :param: requests (list[AgentRequest]): The requests provided to the agent, after pre-hooks.
        :param: agent (Agent): The agent being streamed.
        :param: event (StreamEvent): The event to process, as produced by the runner or by an
                              earlier hook in the chain.
        :return:
                - StreamEvent: The event, or a modified event of the same `type`, to pass on. A
                               different `type` raises TypeError; use a list to emit another type.
                - list[StreamEvent]: Emitted in order, in place of `event`, ending the chain for it.
                - None: Drops the event; nothing is sent to the client for it.
        :raises StreamHalt: To end the run without emitting anything further.
        """
        return event

    @abstractmethod
    def name(self) -> str:
        """
        :return: the name of the posthook.
        """
        raise NotImplementedError
