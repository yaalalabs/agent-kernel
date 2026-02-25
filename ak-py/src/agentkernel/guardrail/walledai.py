import logging
import os
from asyncio import to_thread
from contextlib import redirect_stderr, redirect_stdout

from walledai import WalledProtect, WalledRedact

from ..core.base import Agent, Session
from ..core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestText
from .guardrail import BaseGuardrailUtil, InputGuardrail, OutputGuardrail

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


def silent_call(func, *args, **kwargs):
    """Swallows the SDK's hardcoded print statements."""
    with open(os.devnull, "w") as devnull:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            return func(*args, **kwargs)


class WalledAIGuardrailBase(BaseGuardrailUtil):
    _session_pii_mappings: dict[str, dict] = {}

    def __init__(self):
        self.redact_client = WalledRedact(api_key=os.getenv("WALLED_API_KEY"))
        self.protect_client = WalledProtect(api_key=os.getenv("WALLED_API_KEY"))

class WalledAIInputGuardrail(InputGuardrail, WalledAIGuardrailBase, BaseGuardrailUtil):

    def _handle_exception(self, res):
        warning_msg = "\033[33m[Warning] Input too short for Walled AI check. Bypassing guardrail...\033[0m"
        if isinstance(res, Exception):
            if "INPUT_SHORT" in str(res):
                log.warning(warning_msg)
                return True
            raise res
        return False

    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        raw_text = self._extract_text_from_requests(requests)

        safety_res = await to_thread(silent_call, self.protect_client.guard, raw_text, generic_safety_check=True)

        if self._handle_exception(safety_res):
            return requests
        
        log.debug(f"Walled AI safety response: {safety_res}")

        if isinstance(safety_res, dict) and "data" in safety_res:
            if not safety_res["data"]["safety"][0]["isSafe"]:
                return AgentReplyText(text="I cannot fulfill this request as it violates safety guidelines.")

        redact_res = await to_thread(silent_call, self.redact_client.guard, raw_text)

        if self._handle_exception(redact_res):
            return requests

        if isinstance(redact_res, dict) and "data" in redact_res:
            masked_text = redact_res["data"]["masked_text"]
            new_mapping = redact_res["data"]["mapping"]

            existing_mapping = session._data.get("walledai_pii_mapping", {})
            existing_mapping.update(new_mapping)
            session._data["walledai_pii_mapping"] = existing_mapping

            log.debug(f"Redacted input text: {masked_text}")
            log.debug(f"mapping: {existing_mapping}")

            return [AgentRequestText(text=masked_text)]

        raise ValueError("Received unexpected response format from Walled AI.")


class WalledAIOutputGuardrail(OutputGuardrail, WalledAIGuardrailBase, BaseGuardrailUtil):
    async def on_run(self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply) -> AgentReply:
        masked_output = self._extract_text_from_reply(agent_reply)
        mapping = session._data.get("walledai_pii_mapping", {})

        if not mapping:
            return agent_reply

        unmasked_text = masked_output
        for placeholder, original_value in mapping.items():
            unmasked_text = unmasked_text.replace(placeholder, str(original_value))

        return AgentReplyText(text=unmasked_text)
