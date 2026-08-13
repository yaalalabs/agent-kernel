import logging
import os
from asyncio import to_thread
from contextlib import redirect_stderr, redirect_stdout

from walledai import WalledProtect, WalledRedact

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.model import AgentReply, AgentReplyAny, AgentReplyImage, AgentReplyText, AgentRequest, AgentRequestText
from .guardrail import BaseGuardrailUtil, InputGuardrail, OutputGuardrail

log = logging.getLogger("ak.guardrail.walledai")

WALLEDAI_PII_MAPPING_KEY = "walledai_pii_mapping"


def silent_call(func, *args, **kwargs):
    """
    Execute a callable while suppressing stdout/stderr output.

    This is used to silence hardcoded print statements in the Walled AI SDK
    without affecting guardrail behavior.

    :param func: Callable to execute.
    :param args: Positional arguments for the callable.
    :param kwargs: Keyword arguments for the callable.
    :return: The callable return value.
    """
    with open(os.devnull, "w") as devnull:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            return func(*args, **kwargs)


# We wrap the Walled AI SDK calls in a base class to handle the common logic of suppressing prints and catching exceptions.
class WalledAIGuardrailBase(BaseGuardrailUtil):
    """
    Base class for Walled AI guardrails with shared clients and mapping helpers.
    """

    def __init__(self):
        """
        Initialize Walled AI redact and protect clients.
        """

        api_key = os.getenv("WALLED_API_KEY")
        if not api_key:
            raise RuntimeError("WALLED_API_KEY environment variable is required for Walled AI guardrails.")
        self.redact_client = WalledRedact(api_key=api_key)
        self.protect_client = WalledProtect(api_key=api_key)

    def _get_pii_mapping(self, session: Session) -> dict:
        """
        Retrieve the persisted PII placeholder mapping for the session.

        :param session: Active session containing guardrail state.
        :return: Placeholder-to-original-value mapping.
        :rtype: dict
        """
        mapping = session.get_non_volatile_cache().get(WALLEDAI_PII_MAPPING_KEY, {})
        if isinstance(mapping, dict):
            return mapping
        return {}

    def _set_pii_mapping(self, session: Session, mapping: dict) -> None:
        """
        Persist the PII placeholder mapping for the session.

        :param session: Active session containing guardrail state.
        :param mapping: Placeholder-to-original-value mapping.
        :return: None
        """
        session.get_non_volatile_cache().set(WALLEDAI_PII_MAPPING_KEY, mapping)


# The input guardrail will run both the safety and redaction checks, while the output guardrail will handle unmasking any placeholders in the agent's reply.
class WalledAIInputGuardrail(InputGuardrail, WalledAIGuardrailBase):
    """
    Walled AI input guardrail that performs safety checks and PII redaction.

    Input text is first evaluated for safety, then redacted. The redaction
    mapping is stored in session state for later unmasking on output.
    """

    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        """
        Validate and redact incoming requests before agent execution.

        :param session: Session object containing interaction state.
        :param agent: Agent that will process the sanitized request.
        :param requests: Incoming requests to validate and redact.
        :return: Redacted request list, original requests, or blocked reply.
        :rtype: list[AgentRequest] | AgentReply
        """
        pii_enabled = AKConfig.get().guardrail.input.pii
        if not pii_enabled:
            log.debug("WalledAI PII redaction is disabled for input guardrail.")

        new_requests: list[AgentRequest] = []
        has_text_request = False
        existing_mapping = self._get_pii_mapping(session) if pii_enabled else {}
        mapping_updated = False

        # Process each text request independently so safety and redaction decisions
        # stay aligned with the original request object boundaries.
        for req in requests:
            if not isinstance(req, AgentRequestText):
                new_requests.append(req)
                continue

            has_text_request = True
            raw_text = req.prompt

            if not raw_text:
                new_requests.append(req)
                continue

            try:
                safety_res = await to_thread(silent_call, self.protect_client.guard, raw_text)
            except Exception as e:
                log.error(f"Safety validation error: {e}")
                return AgentReplyText(
                    response="I apologize, but I'm unable to process your request at this time. Please try again later.",
                    prompt=raw_text,
                )

            if isinstance(safety_res, dict) and "data" in safety_res:
                if not safety_res["data"]["safety"][0]["isSafe"]:
                    log.info("Blocked unsafe input due to safety concerns")
                    return AgentReplyText(response="I cannot fulfill this request as it violates safety guidelines.")

            if not pii_enabled:
                new_requests.append(req)
                continue

            try:
                redact_res = await to_thread(silent_call, self.redact_client.guard, raw_text)
            except Exception as e:
                if "INPUT_SHORT" in str(e):
                    log.debug("Input too short for redaction; bypassing for this request.")
                    new_requests.append(req)
                    continue

                log.error(f"Redaction error: {e}")
                return AgentReplyText(
                    response="I apologize, but I'm unable to process your request at this time. Please try again later.",
                    prompt=raw_text,
                )

            if isinstance(redact_res, dict) and "data" in redact_res:
                data = redact_res["data"]
                masked_text = data.get("masked_text", raw_text)
                new_mapping = data.get("mapping", {})
                if isinstance(new_mapping, dict) and new_mapping:
                    existing_mapping.update(new_mapping)
                    mapping_updated = True

                log.debug(f"masked_text: {masked_text}")
                new_requests.append(AgentRequestText(prompt=masked_text))
                continue

            new_requests.append(req)

        if not has_text_request:
            log.debug("No input text found; skipping WalledAI input guardrail checks.")
            return requests

        if pii_enabled and mapping_updated:
            self._set_pii_mapping(session, existing_mapping)
            log.debug(f"existing_mapping: {existing_mapping}")

        return new_requests


class WalledAIOutputGuardrail(OutputGuardrail, WalledAIGuardrailBase):
    """
    Walled AI output guardrail that restores redacted placeholders.

    Uses the session mapping generated during input redaction to replace
    placeholders in the agent reply with original values.
    """

    async def on_run(self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply) -> AgentReply:
        """
        Unmask placeholders in the outgoing agent reply.

        :param session: Session object containing stored PII mappings.
        :param requests: Original requests associated with this reply.
        :param agent: Agent that generated the reply.
        :param agent_reply: Reply potentially containing masked placeholders.
        :return: Unmasked reply when mapping exists; otherwise original reply.
        :rtype: AgentReply
        """
        if not AKConfig.get().guardrail.output.pii:
            log.debug("WalledAI PII unmasking is disabled for output guardrail.")
            return agent_reply

        mapping = self._get_pii_mapping(session)

        if not mapping:
            return agent_reply

        if isinstance(agent_reply, AgentReplyAny):
            return agent_reply.model_copy(update={"content": self._unmask(agent_reply.content, mapping)})

        if isinstance(agent_reply, AgentReplyImage):
            return agent_reply.model_copy(update={"response": self._unmask(agent_reply.response, mapping)})

        if isinstance(agent_reply, AgentReplyText):
            return agent_reply.model_copy(update={"response": self._unmask(agent_reply.response, mapping)})

        # Fallback for unknown reply types
        return agent_reply

    def _unmask(self, value, mapping: dict):
        """
        Recursively replace PII placeholders inside string values.

        Only string values are rewritten, so non-string data (numbers, booleans,
        datetimes, non-string keys) passes through untouched.

        :param value: Content node to unmask (str, dict, list, or any scalar).
        :param mapping: Placeholder-to-original-value mapping.
        :return: Content with placeholders replaced in string values.
        """
        if isinstance(value, str):
            for placeholder, original_value in mapping.items():
                value = value.replace(placeholder, str(original_value))
            return value
        if isinstance(value, dict):
            return {k: self._unmask(v, mapping) for k, v in value.items()}
        if isinstance(value, list):
            return [self._unmask(v, mapping) for v in value]
        return value
