from __future__ import annotations

from ..core.base import Agent, Session
from ..core.model import AgentReply, AgentRequest
from .guardrail import InputGuardrail, OutputGuardrail


class OpenAIInputGuardrail(InputGuardrail):
    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        return requests

    def name(self) -> str:
        return "OpenAIInputGuardrail"


class OpenAIOutputGuardrail(OutputGuardrail):
    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:
        return agent_reply

    def name(self) -> str:
        return "OpenAIOutputGuardrail"
