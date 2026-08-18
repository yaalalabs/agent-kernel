"""End-to-end test of the NATS JetStream queue-mode pipeline against a real server.

The stack (nats-server with JetStream, Valkey) comes from :mod:`nats_tester`; the two pipeline
processes are started the same way you would start them by hand. Beyond the happy path, the last
test feeds the runner a message it cannot parse to prove the retry and termination semantics hold
on a real server: JetStream counts the deliveries, and the message is removed from the work-queue
stream once the pipeline gives up on it.

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
from agentkernel.test import Test

from nats_tester import INPUT_STREAM, OUTPUT_STREAM, NatsTester

API_URL = "http://localhost:8000"
# max_receive_count (2) plus retry_backoff (1 s) from config.yaml, with room for the runner to
# notice and for the error reply to reach the output stream.
TERMINATION_WAIT_SECONDS = 45


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
def nats_stack():
    """The NATS server and Valkey. Streams are created by the pipeline itself, since the example
    runs with auto_provision: true."""
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed or not in PATH")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set; skipping integration test")

    tester = NatsTester()
    tester.up()
    try:
        yield tester
    finally:
        tester.down()


@pytest.fixture(scope="session")
def pipeline(nats_stack):
    """Both pipeline processes: the runner consuming the request stream, the IO side serving REST."""
    runner = _start("runner")
    io_process = _start("io")
    try:
        _wait_for_api()
        yield nats_stack
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
async def test_support_agent_over_nats(client):
    """A rest_sync request: published to a partition subject on AGENT_REQUESTS, answered from
    AGENT_REPLIES via Valkey."""
    response = await client.send("I am Andy Dufresne. I did some deposits.")
    Test.compare(
        response,
        [
            "Hello Andy! I noticed that you made a mobile check deposit of $250. Could you tell me how satisfied "
            "you were with the mobile check deposit process?"
        ],
        threshold=10,
    )


@pytest.mark.asyncio
async def test_session_continues_across_turns(client):
    """A session's turns hash to one partition subject, so they stay ordered behind each other."""
    await client.send("I am Andy Dufresne. I did some deposits.")
    response = await client.send("I was extremely happy")
    Test.compare(
        response,
        ["That's great to hear! What did you like most about the mobile check deposit process?"],
        threshold=10,
    )


def test_streams_and_partition_consumers_exist(pipeline):
    """auto_provision created both work-queue streams with one durable consumer per partition."""
    described = pipeline.describe()

    for stream in (INPUT_STREAM, OUTPUT_STREAM):
        assert described[stream]["exists"], f"{stream} was not provisioned"
        # partitions: 4 in config.yaml
        assert described[stream]["consumers"] == 4, f"{stream} should have one consumer per partition"


def test_unprocessable_message_is_terminated(pipeline):
    """The retry contract on a real server, and the only message guaranteed to sit still long
    enough to inspect: a work-queue stream drops anything the pipeline acks, so a healthy request
    is gone almost immediately, while a message the runner cannot parse lingers through its
    retries. This asserts the wire shape while it lingers, then that JetStream removes it once the
    pipeline terminates it (which is what stops it blocking its partition).
    """
    poison_session = f"poison-{uuid.uuid4().hex[:8]}"
    request_id = str(uuid.uuid4())
    subject = pipeline.publish(
        session=poison_session,
        data=json.dumps({"not_a": "run request"}),
        headers={"request_id": request_id},
    )

    tokens = subject.split(".")  # chat.req.<partition>.<session>
    assert len(tokens) == 4, f"expected a partitioned subject, got {subject}"
    assert tokens[2].isdigit() and int(tokens[2]) < 4, "the session hashed to one of the configured partitions"
    assert tokens[3] == poison_session, "the session id is a single subject token"

    def held():
        return [
            message
            for message in pipeline.tail(INPUT_STREAM)
            if message["headers"].get("Ak-Group-Id") == poison_session
        ]

    in_stream = held()
    assert in_stream, "the injected message should be waiting in the request stream"
    assert in_stream[0]["headers"]["request_id"] == request_id, "routing metadata travels as headers"
    assert in_stream[0]["subject"] == subject

    deadline = time.monotonic() + TERMINATION_WAIT_SECONDS
    while time.monotonic() < deadline and held():
        time.sleep(1)

    assert not held(), f"the poison message was not terminated within {TERMINATION_WAIT_SECONDS} s"
