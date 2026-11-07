"""Live human-approval test for the Claude example: pause, then approve or deny, over the REST API."""

import asyncio
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

HOST, PORT = "localhost", 8000
STARTUP_TIMEOUT = 90
EXECUTED = "DEMO REFUND EXECUTED for"


class APITestClient:
    """Drives one approval exchange on a session of its own: ask, then approve or deny."""

    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def _post(self, payload):
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            # A pause answers 202, not 200: the run has not finished, so this is not an error.
            assert resp.status_code in (200, 202), f"{resp.status_code}: {resp.text}"
            return resp.json()

    async def ask(self, prompt):
        return await self._post({"prompt": prompt, "session_id": self.session_id, "agent": "support"})

    async def decide(self, interruption_id, status, message=None):
        """Answer the pending interruption. No prompt: this turn is the decision, not a new question."""
        decision = {"id": interruption_id, "status": status}
        if message:
            decision["message"] = message
        return await self._post(
            {"session_id": self.session_id, "agent": "support", "resume": {"decisions": [decision]}}
        )


async def _wait_until_serving(proc):
    """Block until the app accepts a connection, or raise if it exits or never serves."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"app.py exited with code {proc.returncode} before it began serving")
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(HOST, PORT), timeout=1)
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.25)
            continue
        writer.close()
        await writer.wait_closed()
        return
    raise RuntimeError(f"app.py did not serve {HOST}:{PORT} within {STARTUP_TIMEOUT}s")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def app_server():
    """Run the app once for the session. Its stderr goes to a file, so tests can check whether the tool ran."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "app.log"
        with log_path.open("w") as log:
            proc = subprocess.Popen([sys.executable, "app.py"], stdout=log, stderr=subprocess.STDOUT)
            try:
                await _wait_until_serving(proc)
                yield f"http://{HOST}:{PORT}", log_path
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                print(log_path.read_text())  # surface the app log in the CI output


@pytest.fixture
def http_client(app_server):
    """A session per test, so an unanswered pause in one test cannot leak into the next."""
    return APITestClient(app_server[0])


@pytest.fixture
def executions(app_server):
    """How many times the gated tool has run for an order, read from the app log."""
    log_path = app_server[1]
    return lambda order_id: log_path.read_text().count(f"{EXECUTED} {order_id}")


@pytest.mark.order(1)
async def test_the_gated_tool_pauses_instead_of_running(http_client, executions):
    body = await http_client.ask("Refund order ORD-1001.")

    assert body["status"] == "PAUSED", body
    assert body["agent"] == "support"
    interruption = body["interruptions"][0]
    assert interruption["kind"] == "tool_call"
    assert interruption["tool_name"] == "issue_refund"
    assert "ORD-1001" in (interruption["arguments"] or "")
    assert executions("ORD-1001") == 0  # paused before the tool ran


@pytest.mark.order(2)
async def test_approving_it_runs_the_tool_once(http_client, executions):
    paused = await http_client.ask("Refund order ORD-1002.")
    assert paused["status"] == "PAUSED", paused
    assert executions("ORD-1002") == 0

    body = await http_client.decide(paused["interruptions"][0]["id"], "approved")

    assert body.get("status") != "PAUSED", body
    assert executions("ORD-1002") == 1
    Test.compare(body["result"], ["The demo refund for ORD-1002 was recorded."], threshold=0.3)


@pytest.mark.order(3)
async def test_denying_it_does_not_run_the_tool(http_client, executions):
    paused = await http_client.ask("Refund order ORD-1003.")
    assert paused["status"] == "PAUSED", paused

    body = await http_client.decide(paused["interruptions"][0]["id"], "denied", message="Refund not permitted")

    assert body.get("status") != "PAUSED", body
    assert executions("ORD-1003") == 0
    Test.compare(body["result"], ["The refund for ORD-1003 was not recorded."], threshold=0.3)
