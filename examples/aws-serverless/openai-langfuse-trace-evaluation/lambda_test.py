import logging
import os
import time

import httpx
import pytest

from simulate_traffic import TrafficSimulator

_log = logging.getLogger("ak.example.trace_evaluation.lambda_test")

WARM_UP_WAIT = 120  # s: lets the warm-up run finish even if the gateway timed out, so every Lambda is warm
INGEST_WAIT = 120  # s: time for Langfuse to store the traces
GRADING_WAIT = 180  # s: time for the grading invocation to judge and store every trace
EXPECTED = len(TrafficSimulator.QUESTIONS)


@pytest.fixture
def chat_url():
    """The deployed agent's /chat URL; skips the test when AK_TEST_ENDPOINT is unset."""
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    if not endpoint:
        pytest.skip("AK_TEST_ENDPOINT is not set; deploy the example first")
    return endpoint.rstrip("/")


def test_every_request_is_graded(chat_url):
    """Sends the questions, starts the evaluation, and expects one graded row per request 3 minutes later."""
    api_url = chat_url.removesuffix("/chat")
    simulator = TrafficSimulator(chat_url)

    _log.info("warming up the agent on a throwaway session")
    simulator.warm_up()
    time.sleep(WARM_UP_WAIT)

    _log.info("session %s: sending %d questions", simulator.session_id, EXPECTED)
    replies = simulator.send_questions()
    assert all(replies), f"expected {EXPECTED} non-empty replies, got {replies}"

    _log.info("waiting %d s for Langfuse to store the traces", INGEST_WAIT)
    time.sleep(INGEST_WAIT)

    response = httpx.post(f"{api_url}/eval", json={"session_id": simulator.session_id}, timeout=30.0)
    assert response.status_code == 202, response.text

    _log.info("waiting %d s for the grading", GRADING_WAIT)
    time.sleep(GRADING_WAIT)

    response = httpx.get(f"{api_url}/check", params={"session_id": simulator.session_id}, timeout=30.0)
    response.raise_for_status()
    graded = response.json()["graded"]
    _log.info("/check: %s of %d requests graded", graded, EXPECTED)
    assert graded == EXPECTED, f"expected {EXPECTED} graded traces, got {graded}"
