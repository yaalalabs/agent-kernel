"""An input guardrail that fails open when the guardrail service itself is unavailable.

Agent Kernel's built-in OpenAI input guardrail fails **closed**: any exception during
validation - a rate limit, an outage, an expired API key - halts the run and returns a
generic apology, so the agent never executes. Its output counterpart already fails open
("On error, allow the reply to proceed rather than blocking"); only the input side does not.

For this system that asymmetry is dangerous. A mother texting "I have heavy bleeding" during
an OpenAI incident would get "I'm unable to process your request at this time." No screening,
no severity, no escalation, and no instruction to contact her PHM. The safety layer sits
upstream of every safeguard in `danger_signs.py` and `escalation.py`, so when it fails closed
it silently disables all of them.

That trade is the same one made for the moderation categories in `guardrails/README.md`:
a narrower net is better than one that can silence a symptom report. A genuine tripwire still
blocks. Only infrastructure failures pass through, and every one is logged.

System pre-hooks run last in the chain, so this cannot be fixed with an ordinary PreHook: the
guardrail would halt the run after ours had already returned. Replacing the guardrail class is
the supported seam - `guardrail.input.type` accepts a dotted path to an `InputGuardrail`
subclass.
"""

from __future__ import annotations

import asyncio
import logging

from agentkernel.core.base import Agent, Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest
from agentkernel.guardrail.openai import OpenAIInputGuardrail

from guardrails import GuardrailTripwireTriggered

log = logging.getLogger("mathru.guardrail")

BLOCKED_MESSAGE = (
    "I apologize, but I'm unable to process this request as it may violate content safety "
    "guidelines. Please rephrase your question or try a different topic."
)


class ResilientInputGuardrail(OpenAIInputGuardrail):
    """Blocks on a real tripwire; passes through when the guardrail service is unreachable."""

    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        if not self._guardrails_client:
            return requests

        input_text = self._extract_text_from_requests(requests)
        if not input_text:
            return requests

        try:
            await asyncio.to_thread(
                self._guardrails_client.chat.completions.create,
                model=AKConfig.get().guardrail.input.model,
                messages=[{"role": "user", "content": input_text}],
                max_tokens=1,
            )
            return requests

        except GuardrailTripwireTriggered as exc:
            # A real safety decision. This still blocks.
            log.warning("Input guardrail triggered: %s", exc)
            return AgentReplyText(response=BLOCKED_MESSAGE, prompt=input_text)

        except Exception as exc:  # noqa: BLE001 - deliberate: availability beats coverage here
            # The guardrail could not reach a verdict. Letting the turn continue means an
            # unscreened message reaches the agent, which is the lesser harm: the danger-sign
            # path, the escalation path and the outbound language hook all still run.
            log.error(
                "Input guardrail unavailable (%s: %s). Failing OPEN so the danger-sign path stays reachable.",
                type(exc).__name__,
                exc,
            )
            return requests

    def name(self) -> str:
        return "ResilientInputGuardrail"
