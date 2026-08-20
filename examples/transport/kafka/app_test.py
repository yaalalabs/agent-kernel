"""End-to-end test of the Kafka queue-mode pipeline against a real broker.

The stack (broker, Valkey, topics) comes from :mod:`kafka_tester`; the two pipeline processes are
started the same way you would start them by hand. Beyond the happy path, the last test feeds the
runner a record it cannot parse to prove the retry and dead-letter semantics hold on a real
broker, not just against a test double.

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

from kafka_tester import INPUT_TOPIC, OUTPUT_TOPIC, KafkaTester

API_URL = "http://localhost:8000"
# max_receive_count (2) + retry_backoff (1s) from config.yaml, plus room for the runner to notice.
DLQ_WAIT_SECONDS = 30


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
def kafka_stack():
    """The broker, Valkey, and the provisioned topics."""
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed or not in PATH")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set; skipping integration test")

    tester = KafkaTester()
    tester.up()
    try:
        yield tester
    finally:
        tester.down()


@pytest.fixture(scope="session")
def pipeline(kafka_stack):
    """Both pipeline processes: the runner consuming the input topic, the IO side serving REST.

    Deliberately a synchronous fixture: the sync topic-inspection tests need it too, and nothing
    in the startup sequence awaits anything.
    """
    runner = _start("runner")
    io_process = _start("io")
    try:
        _wait_for_api()
        yield kafka_stack
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
async def test_support_agent_over_kafka(client):
    """A rest_sync request: enqueued on agent-input, answered from agent-output via Valkey."""
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
    """The session id is the record key, so a session's turns stay ordered on one partition."""
    await client.send("I am Andy Dufresne. I did some deposits.")
    response = await client.send("I was extremely happy")
    Test.compare(
        response,
        ["That's great to hear! What did you like most about the mobile check deposit process?"],
        threshold=0.1,
    )


@pytest.mark.asyncio
async def test_messages_flow_through_the_topics(pipeline, client):
    """Both queues carry traffic, and the request id travels as a record header.

    Sends its own request so it does not depend on the order of the tests above.
    """
    await client.send("Hello")

    records = [record for record in pipeline.tail(INPUT_TOPIC, timeout=5.0) if record["key"] == client.session_id]
    assert records, "the request handler produced nothing to the input topic"
    assert all("request_id" in record["headers"] for record in records)
    assert all(record["key"] for record in records), "every record is keyed by its session id"

    assert pipeline.tail(OUTPUT_TOPIC, timeout=5.0), "the agent runner produced nothing to the output topic"


def test_unprocessable_record_lands_in_the_dead_letter_topic(pipeline):
    """The retry contract on a real broker: a record the runner cannot parse is retried up to
    max_receive_count, then routed to <topic>.dlq with an ak-error header, and committed so it
    stops blocking its partition."""
    poison_session = f"poison-{uuid.uuid4()}"
    pipeline.produce(
        INPUT_TOPIC,
        value=json.dumps({"not_a": "run request"}),
        key=poison_session,
        headers={"request_id": str(uuid.uuid4())},
    )

    deadline = time.monotonic() + DLQ_WAIT_SECONDS
    dead_lettered = []
    while time.monotonic() < deadline and not dead_lettered:
        dead_lettered = [
            record for record in pipeline.tail(f"{INPUT_TOPIC}.dlq", timeout=2.0) if record["key"] == poison_session
        ]

    assert dead_lettered, f"the poison record never reached {INPUT_TOPIC}.dlq within {DLQ_WAIT_SECONDS} s"
    assert "ak-error" in dead_lettered[0]["headers"]
    assert "request_id" in dead_lettered[0]["headers"], "the original headers travel to the DLQ"
