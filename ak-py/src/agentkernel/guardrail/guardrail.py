from __future__ import annotations

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.hooks import PostHook, PreHook
from ..core.model import AgentReply, AgentReplyAny, AgentReplyImage, AgentReplyText, AgentRequest, AgentRequestText, AgentResumeRequestAny
from ..core.util.factory import AKConfigError, require_extra, resolve_dotted

_BUILTIN_GUARDRAILS = ["openai", "bedrock", "walledai"]


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
        config = AKConfig.get().guardrail.input
        if not config.enabled:
            return InputGuardrail()  # OFF: pass-through hook
        gtype = config.type
        if gtype == "openai":
            with require_extra("openai", "guardrail.input.type: openai"):
                from .openai import OpenAIInputGuardrail

            return OpenAIInputGuardrail()
        if gtype == "bedrock":
            with require_extra("aws", "guardrail.input.type: bedrock"):
                from .bedrock import BedrockInputGuardrail

            return BedrockInputGuardrail()
        if gtype == "walledai":
            with require_extra("walledai", "guardrail.input.type: walledai"):
                from .walledai import WalledAIInputGuardrail

            return WalledAIInputGuardrail()
        if "." not in gtype:
            raise AKConfigError(
                f"unknown guardrail type '{gtype}'; expected one of {_BUILTIN_GUARDRAILS} or a dotted path to an InputGuardrail subclass"
            )
        return resolve_dotted(gtype, base=InputGuardrail)()


class OutputGuardrailFactory:

    @staticmethod
    def get() -> PostHook:
        config = AKConfig.get().guardrail.output
        if not config.enabled:
            return OutputGuardrail()  # OFF: pass-through hook
        gtype = config.type
        if gtype == "openai":
            with require_extra("openai", "guardrail.output.type: openai"):
                from .openai import OpenAIOutputGuardrail

            return OpenAIOutputGuardrail()
        if gtype == "bedrock":
            with require_extra("aws", "guardrail.output.type: bedrock"):
                from .bedrock import BedrockOutputGuardrail

            return BedrockOutputGuardrail()
        if gtype == "walledai":
            with require_extra("walledai", "guardrail.output.type: walledai"):
                from .walledai import WalledAIOutputGuardrail

            return WalledAIOutputGuardrail()
        if "." not in gtype:
            raise AKConfigError(
                f"unknown guardrail type '{gtype}'; expected one of {_BUILTIN_GUARDRAILS} or a dotted path to an OutputGuardrail subclass"
            )
        return resolve_dotted(gtype, base=OutputGuardrail)()


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
                text_parts.append(req.prompt)
            elif isinstance(req, AgentResumeRequestAny):
                text_parts.extend(BaseGuardrailUtil._extract_text_from_decisions(req))
        return "\n".join(text_parts)

    @staticmethod
    def _extract_text_from_decisions(resume: AgentResumeRequestAny) -> list[str]:
        """
        Extract the human's own words from a resume request, so a guardrail sees them.

        A decision's free text reaches the model exactly as a prompt does, so skipping it would
        leave a route no input guardrail inspects. Only string payload values are taken: a guardrail
        scanning arbitrary nested JSON reports ids and enum values as findings.

        :param resume: The resume request carrying the decisions.
        :return: The text a human typed, one entry per value.
        """
        text_parts = []
        for decision in resume.decisions:
            if decision.message:
                text_parts.append(decision.message)
            if decision.payload:
                text_parts.extend(value for value in decision.payload.values() if isinstance(value, str))
        return text_parts

    @staticmethod
    def _extract_text_from_reply(agent_reply: AgentReply) -> str:
        """
        Extract text content from agent reply.
        :param agent_reply: Agent reply
        """
        if isinstance(agent_reply, AgentReplyText):
            return agent_reply.response
        elif isinstance(agent_reply, AgentReplyAny):
            return str(agent_reply)
        elif isinstance(agent_reply, AgentReplyImage):
            return str(agent_reply.response)
        return ""
