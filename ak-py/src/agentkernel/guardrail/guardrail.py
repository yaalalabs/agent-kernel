from __future__ import annotations

from ..core.base import Agent, Session
from ..core.hooks import PostHook, PreHook
from ..core.model import AgentReply, AgentRequest


class InputGuardrail(PreHook):
    async def on_run(
            self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        return requests

    def name(self) -> str:
        return "InputGuardrail"


class OutputGuardrail(PostHook):
    async def on_run(
            self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:

        return agent_reply

    def name(self) -> str:
        return "OutputGuardrail"
