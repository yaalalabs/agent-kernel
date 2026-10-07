import logging
import os
from asyncio import to_thread
from contextlib import redirect_stderr, redirect_stdout

from pydantic import JsonValue
from walledai import WalledProtect, WalledRedact

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.model import (
    AgentReply,
    AgentReplyAny,
    AgentReplyImage,
    AgentReplyText,
    AgentRequest,
    AgentRequestText,
    AgentResumeRequestAny,
)
from .guardrail import BaseGuardrailUtil, InputGuardrail, OutputGuardrail

log = logging.getLogger("ak.guardrail.walledai")

WALLEDAI_PII_MAPPING_KEY = "walledai_pii_mapping"
WALLEDAI_UNAVAILABLE_REPLY = "I apologize, but I'm unable to process your request at this time. Please try again later."


class _GuardBlocked(Exception):
    """
    Carries the reply a blocked or failed check has to return.

    Raised rather than returned so the per-string helper can stop the whole request list from one
    level down, without every caller threading a "did this block?" value back up.
    """

    def __init__(self, reply: AgentReplyText) -> None:
        super().__init__(reply.response)
        self.reply = reply


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


def _mask_payload(payload: JsonValue, replacements: dict[str, str]) -> JsonValue:
    """
    Substitute the redacted form of every string the payload exposes, leaving its shape untouched.

    Mirrors `BaseGuardrailUtil._payload_text`, which chose those strings — one level, strings only.

    :param payload: The original decision payload.
    :param replacements: Original string to its redacted form.
    :return: The payload with its human-written strings replaced.
    """
    if isinstance(payload, str):
        return replacements.get(payload, payload)
    if isinstance(payload, list):
        return [replacements.get(v, v) if isinstance(v, str) else v for v in payload]
    if isinstance(payload, dict):
        return {k: replacements.get(v, v) if isinstance(v, str) else v for k, v in payload.items()}
    return payload


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

        Covers a resume as well as a prompt: a human's decision text reaches the model exactly as a
        prompt does, so leaving it out would make this the one input guardrail a decision bypasses.

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

        # Each request is processed independently so safety and redaction decisions stay aligned
        # with the original request object boundaries.
        try:
            for req in requests:
                if isinstance(req, AgentRequestText):
                    if not req.prompt:
                        new_requests.append(req)
                        continue
                    has_text_request = True
                    masked, updated = await self._guard_text(req.prompt, pii_enabled, existing_mapping)
                    mapping_updated = mapping_updated or updated
                    new_requests.append(AgentRequestText(prompt=masked) if masked != req.prompt else req)
                elif isinstance(req, AgentResumeRequestAny):
                    guarded, saw_text, updated = await self._guard_resume(req, pii_enabled, existing_mapping)
                    has_text_request = has_text_request or saw_text
                    mapping_updated = mapping_updated or updated
                    new_requests.append(guarded)
                else:
                    new_requests.append(req)
        except _GuardBlocked as blocked:
            return blocked.reply

        if not has_text_request:
            log.debug("No input text found; skipping WalledAI input guardrail checks.")
            return requests

        if pii_enabled and mapping_updated:
            self._set_pii_mapping(session, existing_mapping)
            log.debug(f"existing_mapping: {existing_mapping}")

        return new_requests

    async def _guard_text(self, raw_text: str, pii_enabled: bool, mapping: dict) -> tuple[str, bool]:
        """
        Run one string through the safety check and, when enabled, PII redaction.

        Every text-bearing request funnels through here, so a request type added later cannot reach
        the model with one of the two checks quietly skipped.

        :param raw_text: The string to check.
        :param pii_enabled: Whether PII redaction is configured on.
        :param mapping: Placeholder-to-original mapping, updated in place when redaction runs.
        :return: The text to send onward, and whether the mapping gained entries.
        :raises _GuardBlocked: If the text is unsafe, or a Walled AI call failed.
        """
        try:
            safety_res = await to_thread(silent_call, self.protect_client.guard, raw_text)
        except Exception as e:
            log.error(f"Safety validation error: {e}")
            raise _GuardBlocked(AgentReplyText(response=WALLEDAI_UNAVAILABLE_REPLY, prompt=raw_text)) from e

        if isinstance(safety_res, dict) and "data" in safety_res:
            if not safety_res["data"]["safety"][0]["isSafe"]:
                log.info("Blocked unsafe input due to safety concerns")
                raise _GuardBlocked(AgentReplyText(response="I cannot fulfill this request as it violates safety guidelines."))

        if not pii_enabled:
            return raw_text, False

        try:
            redact_res = await to_thread(silent_call, self.redact_client.guard, raw_text)
        except Exception as e:
            if "INPUT_SHORT" in str(e):
                log.debug("Input too short for redaction; bypassing for this request.")
                return raw_text, False
            log.error(f"Redaction error: {e}")
            raise _GuardBlocked(AgentReplyText(response=WALLEDAI_UNAVAILABLE_REPLY, prompt=raw_text)) from e

        if isinstance(redact_res, dict) and "data" in redact_res:
            data = redact_res["data"]
            masked_text = data.get("masked_text", raw_text)
            new_mapping = data.get("mapping", {})
            updated = isinstance(new_mapping, dict) and bool(new_mapping)
            if updated:
                mapping.update(new_mapping)
            log.debug(f"masked_text: {masked_text}")
            return masked_text, updated

        return raw_text, False

    async def _guard_resume(self, resume: AgentResumeRequestAny, pii_enabled: bool, mapping: dict) -> tuple[AgentResumeRequestAny, bool, bool]:
        """
        Run a human's decision text through the same checks a prompt gets.

        The strings guarded are the ones `_payload_text` reads, so what this guardrail rewrites and
        what the shared extractor inspects cannot drift apart. Everything else in a payload is left
        alone: masking an interruption id or an enum value would break the answer the framework is
        waiting for, and `status` is a fixed verb with nothing human in it.

        :param resume: The resume request to guard.
        :param pii_enabled: Whether PII redaction is configured on.
        :param mapping: Placeholder-to-original mapping, updated in place.
        :return: The guarded request, whether it carried any text, and whether the mapping grew.
        :raises _GuardBlocked: If any decision's text is unsafe, or a Walled AI call failed.
        """
        replacements: dict[str, str] = {}
        mapping_updated = False
        for decision in resume.decisions:
            texts = ([decision.message] if decision.message else []) + self._payload_text(decision.payload)
            for text in texts:
                if not text or text in replacements:
                    continue
                replacements[text], updated = await self._guard_text(text, pii_enabled, mapping)
                mapping_updated = mapping_updated or updated

        if not replacements:
            return resume, False, False

        decisions = [
            decision.model_copy(
                update={
                    "message": replacements.get(decision.message, decision.message) if decision.message else decision.message,
                    "payload": _mask_payload(decision.payload, replacements),
                }
            )
            for decision in resume.decisions
        ]
        return resume.model_copy(update={"decisions": decisions}), True, mapping_updated


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
