from __future__ import annotations

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.hooks import PostHook, PreHook
from ..core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestText


class InputGuardrail(PreHook):
    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        return requests

    def name(self) -> str:
        return "InputGuardrail"


class OutputGuardrail(PostHook):
    async def on_run(self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply) -> AgentReply:
        return agent_reply

    def name(self) -> str:
        return "OutputGuardrail"


class InputGuardrailFactory:

    @staticmethod
    def get() -> PreHook:
        if AKConfig.get().guardrail.input.enabled:
            if AKConfig.get().guardrail.input.type == "openai":
                from .openai import OpenAIInputGuardrail

                return OpenAIInputGuardrail()
            elif AKConfig.get().guardrail.input.type == "bedrock":
                from .bedrock import BedrockInputGuardrail

                return BedrockInputGuardrail()
            else:
                raise Exception(f"Unknown guardrail type: {AKConfig.get().guardrail.input.type}")
        else:
            return InputGuardrail()


class OutputGuardrailFactory:

    @staticmethod
    def get() -> PostHook:
        if AKConfig.get().guardrail.output.enabled:
            if AKConfig.get().guardrail.output.type == "openai":
                from .openai import OpenAIOutputGuardrail

                return OpenAIOutputGuardrail()
            elif AKConfig.get().guardrail.output.type == "bedrock":
                from .bedrock import BedrockOutputGuardrail

                return BedrockOutputGuardrail()
            else:
                raise Exception(f"Unknown guardrail type: {AKConfig.get().guardrail.output.type}")
        else:
            return OutputGuardrail()


class BaseGuardrailUtil:
    """
    Utility class providing common text extraction utilities for guardrails.
    """

    @staticmethod
    def _extract_text_from_requests(requests: list[AgentRequest]) -> str:
        """
        Extract text content from agent requests.
        :param requests: List of agent requests
        """
        text_parts = []
        for req in requests:
            if isinstance(req, AgentRequestText):
                text_parts.append(req.text)
            elif hasattr(req, "text"):
                text_parts.append(str(req.text))
        return "\n".join(text_parts)

    @staticmethod
    def _extract_text_from_reply(agent_reply: AgentReply) -> str:
        """
        Extract text content from agent reply.
        :param agent_reply: Agent reply
        """
        if isinstance(agent_reply, AgentReplyText):
            return agent_reply.text
        elif hasattr(agent_reply, "text"):
            return str(agent_reply.text)
        return ""
