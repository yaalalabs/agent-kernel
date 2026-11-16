"""End-to-end test of the Pub/Sub queue-mode pipeline against the Pub/Sub emulator.

The stack (the emulator and Valkey) comes from :mod:`pubsub_tester`; the two pipeline processes
are started the same way you would start them by hand. Beyond the happy path, the last test feeds
the runner a message it cannot parse, to prove the retry and dead-letter semantics hold on a real
Pub/Sub implementation: the transport counts the deliveries, and once the pipeline gives up the
message is copied to the dead-letter topic with the reason attached.

Skipped when Docker or an OpenAI key is unavailable.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import httpx
import pytest
from agentkernel.core.config import AKConfig
from agentkernel.test import Test

from pubsub_tester import DLQ_SUFFIX, INPUT_TOPIC, OUTPUT_TOPIC, PubSubTester

# The port the io process serves on: config.yaml's api.port, or AK_API__PORT when set.
API_URL = f"http://localhost:{AKConfig.get().api.port}"
# max_receive_count (2) with immediate redelivery (auto_provision sets no retry policy), with room
# for the runner to notice and for the copy to reach the dead-letter topic.
DEAD_LETTER_WAIT_SECONDS = 45


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt):
        payload = {"prompt": prompt, "session_id": self.session_id, "agent": "support"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("result", "")


def _start(role: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "app.py", role], stdout=sys.stdout, stderr=sys.stderr)


def _wait_for_api(timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{API_URL}/health", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(1)
    raise TimeoutError("the pipeline's REST API never became healthy")


@pytest.fixture(scope="session")
def pubsub_stack():
    """The emulator and Valkey. Topics are created by the pipeline itself, since the example runs
    with auto_provision: true."""
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed or not in PATH")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set; skipping integration test")

    tester = PubSubTester()
    tester.up()
    try:
        yield tester
    finally:
        tester.down()


@pytest.fixture(scope="session")
def pipeline(pubsub_stack):
    """Both pipeline processes: the runner pulling requests, the IO side serving REST."""
    runner = _start("runner")
    io_process = _start("io")
    try:
        _wait_for_api()
        yield pubsub_stack
    finally:
        for process in (io_process, runner):
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.fixture
def client(pipeline):
    return APITestClient(API_URL)


@pytest.mark.asyncio
async def test_support_agent_over_pubsub(client):
    """A rest_sync request: published to agent-input, answered from agent-output via Valkey."""
    response = await client.send("I am Andy Dufresne. I did some deposits.")
    Test.compare(
        response,
        [
            "Hello Andy! I noticed that you made a mobile check deposit of $250. Could you tell me how satisfied "
            "you were with the mobile check deposit process?"
        ],
        threshold=0.1,
    )


@pytest.mark.asyncio
async def test_session_continues_across_turns(client):
    """A session's turns share an ordering key, so they run one after the other, in order."""
    await client.send("I am Andy Dufresne. I did some deposits.")
    response = await client.send("I was extremely happy")
    Test.compare(
        response,
        ["That's great to hear! What did you like most about the mobile check deposit process?"],
        threshold=0.1,
    )


def test_topics_and_subscriptions_were_provisioned(pipeline):
    """auto_provision created both queues with ordering and a dead-letter policy, plus a
    subscription on each dead-letter topic so the copies are kept."""
    described = pipeline.describe()

    for topic in (INPUT_TOPIC, OUTPUT_TOPIC):
        assert described[topic]["exists"], f"{topic} was not provisioned"
        settings = described[topic]["subscriptions"][topic]
        assert settings["ordering"] is True, f"{topic} must have message ordering enabled"
        assert settings["dead_letter_topic"] == f"{topic}{DLQ_SUFFIX}"
        assert described[f"{topic}{DLQ_SUFFIX}"][
            "subscriptions"
        ], f"{topic}{DLQ_SUFFIX} needs a subscription to keep copies"


def test_unprocessable_message_reaches_the_dead_letter_topic(pipeline):
    """The retry contract on a real Pub/Sub implementation: a message the runner cannot parse is
    retried max_receive_count times, then copied to agent-input-dlq with the reason attached."""
    poison_session = f"poison-{uuid.uuid4().hex[:8]}"
    request_id = str(uuid.uuid4())
    pipeline.publish(
        session=poison_session, data=json.dumps({"not_a": "run request"}), attributes={"request_id": request_id}
    )

    def dead_lettered():
        return [
            message
            for message in pipeline.tail(f"{INPUT_TOPIC}{DLQ_SUFFIX}")
            if message["ordering_key"] == ""
            and message.get("envelope", {}).get("attributes", {}).get("request_id") == request_id
        ]

    deadline = time.monotonic() + DEAD_LETTER_WAIT_SECONDS
    copies = dead_lettered()
    while time.monotonic() < deadline and not copies:
        time.sleep(1)
        copies = dead_lettered()

    assert copies, f"the poison message was not dead-lettered within {DEAD_LETTER_WAIT_SECONDS} s"
    assert copies[0]["attributes"]["ak-error"].startswith("exceeded max_receive_count")
    assert json.loads(copies[0]["envelope"]["body"]) == {"not_a": "run request"}, "the copy keeps the original message"
