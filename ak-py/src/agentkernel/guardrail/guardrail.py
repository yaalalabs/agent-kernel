from __future__ import annotations

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.hooks import PostHook, PreHook
from ..core.model import AgentReply, AgentRequest


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
            else:
                raise Exception(f"Unknown guardrail type: {AKConfig.get().guardrail.output.type}")
        else:
            return OutputGuardrail()
