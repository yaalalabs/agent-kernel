"""Tests for the fail-open input guardrail.

The rule: a real tripwire blocks, an unreachable guardrail service does not. Failing closed
here would take the danger-sign path down with it, since the guardrail runs upstream of every
safeguard in the system.
"""

import logging

import pytest
from agentkernel.core.model import AgentReplyText, AgentRequestText

import resilient_guardrail
from guardrails import GuardrailTripwireTriggered


class FakeCompletions:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return object()


class FakeClient:
    def __init__(self, error=None):
        self.chat = type("Chat", (), {"completions": FakeCompletions(error)})()


def build(error=None, client=True):
    guardrail = resilient_guardrail.ResilientInputGuardrail.__new__(resilient_guardrail.ResilientInputGuardrail)
    guardrail._guardrails_client = FakeClient(error) if client else None
    return guardrail


REQUESTS = [AgentRequestText(prompt="I have heavy bleeding")]


async def run(guardrail, requests=None):
    return await guardrail.on_run(session=None, agent=None, requests=requests if requests is not None else REQUESTS)


# --- a real tripwire still blocks --------------------------------------------------------


async def test_a_tripwire_blocks_the_request():
    result = await run(build(error=GuardrailTripwireTriggered("jailbreak")))
    assert isinstance(result, AgentReplyText)
    assert result.response == resilient_guardrail.BLOCKED_MESSAGE


# --- infrastructure failures fail open ---------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Error code: 429 - credit_balance_exhausted"),
        ConnectionError("network unreachable"),
        TimeoutError("timed out"),
        Exception("something unexpected"),
    ],
)
async def test_an_unreachable_guardrail_lets_the_turn_continue(error):
    # The exact case seen in the wild: no credits, three retries, then a generic apology that
    # would have replaced a symptom report's screening.
    result = await run(build(error=error))
    assert result is REQUESTS


async def test_failing_open_is_logged_as_an_error(caplog):
    with caplog.at_level(logging.ERROR, logger="mathru.guardrail"):
        await run(build(error=RuntimeError("429")))

    assert any("Failing OPEN" in record.message for record in caplog.records)


async def test_a_symptom_report_survives_a_guardrail_outage():
    # The whole point. This message must reach danger_sign_agent.
    requests = [AgentRequestText(prompt="I have heavy bleeding and severe pain")]
    result = await run(build(error=RuntimeError("Error code: 429")), requests)
    assert result is requests
    assert not isinstance(result, AgentReplyText)


# --- pass-through cases ------------------------------------------------------------------


async def test_a_clean_request_passes():
    assert await run(build()) is REQUESTS


async def test_no_client_configured_passes_through():
    assert await run(build(client=False)) is REQUESTS


async def test_empty_text_is_not_sent_to_the_guardrail():
    guardrail = build()
    requests = [AgentRequestText(prompt="")]
    assert await run(guardrail, requests) is requests
    assert guardrail._guardrails_client.chat.completions.calls == 0


def test_the_guardrail_reports_its_name():
    assert build().name() == "ResilientInputGuardrail"
