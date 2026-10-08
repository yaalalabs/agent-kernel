"""Smoke tests for the deployed Slack example. They need no Slack workspace.

Set:
- AK_TEST_ENDPOINT: the module's `agent_invoke_url` output (the chat route). The Slack route is
  derived from it, since both live behind the same API Gateway stage.
- AK_TEST_TOKEN: the `demo_auth_token` the stack was deployed with.
- SLACK_SIGNING_SECRET: the signing secret the stack was deployed with.

Each check proves one hop of the edge: the chat route still authorizes, the authorizer's bypass
lets the Slack route through to Bolt, and a correctly signed Slack delivery is answered.
"""

import hashlib
import hmac
import json
import os
import time

import httpx
import pytest

ENDPOINT = os.getenv("AK_TEST_ENDPOINT", "")
TOKEN = os.getenv("AK_TEST_TOKEN", "")
SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

pytestmark = pytest.mark.skipif(not ENDPOINT, reason="Set AK_TEST_ENDPOINT to the deployment's agent_invoke_url")


def _slack_url() -> str:
    # /api/v1/chat -> /api/v1/slack/events
    return ENDPOINT.rstrip("/").rsplit("/", 1)[0] + "/slack/events"


def _signed_headers(body: str) -> dict:
    timestamp = str(int(time.time()))
    digest = hmac.new(SIGNING_SECRET.encode(), f"v0:{timestamp}:{body}".encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": f"v0={digest}",
    }


def _post(url: str, content: str, headers: dict) -> httpx.Response:
    # Retry a gateway timeout or 5xx: a cold start can exceed API Gateway's limit on the first call.
    response = None
    for _ in range(3):
        try:
            response = httpx.post(url, content=content, headers=headers, timeout=30.0)
        except httpx.TimeoutException:
            continue
        if response.status_code < 500:
            return response
        time.sleep(5)
    assert response is not None, f"no response from {url}"
    return response


def test_the_chat_route_still_needs_a_token():
    body = json.dumps({"prompt": "hi", "session_id": "smoke-1", "request_id": f"smoke-{time.time_ns()}"})

    assert _post(ENDPOINT, body, {"Content-Type": "application/json"}).status_code in (401, 403)

    assert TOKEN, "Set AK_TEST_TOKEN to the deployed demo_auth_token"
    response = _post(ENDPOINT, body, {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200, response.text


def test_the_bypass_lets_an_unsigned_slack_delivery_reach_bolt():
    response = _post(_slack_url(), json.dumps({"type": "event_callback"}), {"Content-Type": "application/json"})

    # Bolt's rejection, not API Gateway's {"message": "Unauthorized"}: the request got past the
    # authorizer and failed Slack's signature check in the request handler.
    assert response.status_code == 401, response.text
    assert response.json() == {"error": "invalid request"}


def test_a_signed_url_verification_is_answered():
    assert SIGNING_SECRET, "Set SLACK_SIGNING_SECRET to the deployed signing secret"
    body = json.dumps({"type": "url_verification", "challenge": "smoke-challenge", "token": "unused"})

    response = _post(_slack_url(), body, _signed_headers(body))

    assert response.status_code == 200, response.text
    assert response.json() == {"challenge": "smoke-challenge"}
