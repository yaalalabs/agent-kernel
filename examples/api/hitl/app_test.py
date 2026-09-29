import asyncio
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


class APITestClient:
    """Drives the three-step human-in-the-loop exchange: ask, approve or deny, read the answer."""

    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def _post(self, payload):
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            # A pause answers 202, not 200 — the run has not finished, so this is not an error.
            assert resp.status_code in (200, 202), f"{resp.status_code}: {resp.text}"
            return resp.json()

    async def ask(self, prompt, agent="support"):
        """Send a prompt. Returns the whole body, so the caller can branch on `status`."""
        return await self._post({"prompt": prompt, "session_id": self.session_id, "agent": agent})

    async def decide(self, interruption_id, status, message=None):
        """Answer one pending interruption. No prompt: this turn is the decision, not a new question."""
        decision = {"id": interruption_id, "status": status}
        if message:
            decision["message"] = message
        return await self._post(
            {"session_id": self.session_id, "agent": "support", "resume": {"decisions": [decision]}}
        )

    async def answer(self, interruption_id, value, agent="planner"):
        """Supply a *value* — a chosen option or free text — rather than a verdict."""
        return await self._post(
            {
                "session_id": self.session_id,
                "agent": agent,
                "resume": {"decisions": [{"id": interruption_id, "payload": value}]},
            }
        )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    proc = subprocess.Popen(["python3", "app.py"], stdout=sys.stdout, stderr=sys.stderr)
    await asyncio.sleep(5)
    try:
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_the_gated_tool_pauses_instead_of_running(http_client):
    """The agent stops before `issue_refund` and reports what it wants to do."""
    body = await http_client.ask("Please refund order ORD-1001.")

    assert body["status"] == "PAUSED", body
    assert body["agent"] == "support"
    assert body["run_id"]

    interruption = body["interruptions"][0]
    assert interruption["kind"] == "tool_call"
    assert interruption["tool_name"] == "issue_refund"
    # The arguments are what a human needs in order to judge the call.
    assert "ORD-1001" in (interruption["arguments"] or "")


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_approving_it_runs_the_tool(http_client):
    """The second turn carries only the decision, and the refund actually happens."""
    paused = await http_client.ask("Please refund order ORD-1002.")
    interruption_id = paused["interruptions"][0]["id"]

    body = await http_client.decide(interruption_id, "approved")

    assert body.get("status") != "PAUSED", body
    Test.compare(body["result"], ["the refund of $980.00 for ORD-1002 was issued"], threshold=0.3)


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_denying_it_does_not_run_the_tool(http_client):
    """A denial must not come back as a success: the human's reason reaches the model."""
    paused = await http_client.ask("Please refund order ORD-1001.")
    interruption_id = paused["interruptions"][0]["id"]

    body = await http_client.decide(interruption_id, "denied", message="Outside the 30-day refund window.")

    assert body.get("status") != "PAUSED", body
    Test.compare(body["result"], ["the refund was not issued because it is outside the refund window"], threshold=0.3)


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_an_ungated_tool_still_answers_in_one_turn(http_client):
    """`lookup_order` needs no approval, so nothing pauses."""
    body = await http_client.ask("How much is order ORD-1001 refundable for?")

    assert body.get("status") != "PAUSED", body
    Test.compare(body["result"], ["ORD-1001 is refundable for $42.50"], threshold=0.3)


# --- LangGraph: the questions OpenAI cannot ask ------------------------------------------------
#
# The OpenAI SDK records an approval as a boolean, so a gated tool can only be approved or denied.
# Asking someone to *choose* or to *type* needs a framework whose pause carries a value back.


@pytest.mark.asyncio
@pytest.mark.order(5)
async def test_a_choice_comes_back_with_its_options(http_client):
    body = await http_client.ask("Plan the refund for ORD-1001.", agent="planner")

    assert body["status"] == "PAUSED", body
    interruption = body["interruptions"][0]
    # `input_required`, not `tool_call`: the agent wants a value, not permission.
    assert interruption["kind"] == "input_required"
    assert interruption["payload"]["options"] == ["Original card", "Store credit", "Bank transfer"]


@pytest.mark.asyncio
@pytest.mark.order(6)
async def test_answering_the_choice_asks_the_free_text_question(http_client):
    """Two interrupts in one node: the second is reached only once the first has an answer."""
    paused = await http_client.ask("Plan the refund for ORD-1002.", agent="planner")

    body = await http_client.answer(paused["interruptions"][0]["id"], "Store credit")

    assert body["status"] == "PAUSED", body
    assert "free text" in body["interruptions"][0]["payload"]["question"]
    assert "options" not in body["interruptions"][0]["payload"]


@pytest.mark.asyncio
@pytest.mark.order(7)
async def test_both_answers_reach_the_model(http_client):
    """The chosen option and the typed note both land in the confirmation the model writes."""
    paused = await http_client.ask("Plan the refund for ORD-1001.", agent="planner")
    second = await http_client.answer(paused["interruptions"][0]["id"], "Bank transfer")

    body = await http_client.answer(second["interruptions"][0]["id"], "Apologise for the delay.")

    assert body.get("status") != "PAUSED", body
    Test.compare(
        body["result"], ["the refund will be returned by bank transfer, with an apology for the delay"], threshold=0.3
    )
