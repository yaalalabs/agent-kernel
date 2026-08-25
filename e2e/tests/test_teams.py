"""End-to-end test for the Microsoft Teams integration.

Teams itself has no API that lets a *user* account send a message to a bot, so the round
trip is driven through the same Azure Bot resource's **Direct Line** channel instead. The
activity is signed and delivered by the real Bot Framework service, so this exercises the
same code path a Teams message takes: JWT validation on the webhook, the proactive
`continue_conversation` follow-up the handler uses to run the agent outside the delivery
window, and the reply going back out through the connector.

What it does not cover is attachment handling: Direct Line serves attachments from its own
hosts, not the `smba.trafficmanager.net` / SharePoint hosts Teams uses, so the attachment
authorization path stays manual-only (see e2e/README.md).

Required environment variables:
- E2E_TEAMS_DIRECTLINE_SECRET: a Direct Line channel secret from the Azure Bot resource
  (Channels > Direct Line > Site > Secret keys).
"""

import time
import uuid

import httpx
from conftest import POLL_INTERVAL_SECONDS, REPLY_TIMEOUT_SECONDS, require_env

DIRECT_LINE_BASE_URL = "https://directline.botframework.com/v3/directline"
USER_ID = "e2e-tester"

# Fallbacks the handler sends when the transport worked but the agent run did not; a reply
# matching one of these means the webhook and connector are fine and the agent errored.
TEAMS_ERROR_FALLBACKS = {
    "No agent available to handle your request.",
    "Please provide a message or attachment.",
    "Error sending agent response.",
    "The agent returned an empty response.",
    "Sorry, an error occurred while processing your request.",
    "Sorry Alice, an error occurred while processing your request.",
}


def _start_conversation(client: httpx.Client) -> str:
    response = client.post(f"{DIRECT_LINE_BASE_URL}/conversations")
    response.raise_for_status()
    return response.json()["conversationId"]


def _send(client: httpx.Client, conversation_id: str, prompt: str) -> None:
    response = client.post(
        f"{DIRECT_LINE_BASE_URL}/conversations/{conversation_id}/activities",
        json={"type": "message", "from": {"id": USER_ID}, "text": prompt},
    )
    response.raise_for_status()


def _await_reply(client: httpx.Client, conversation_id: str) -> str | None:
    """Poll the conversation until the bot posts a non-empty message of its own."""
    watermark = None
    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        params = {"watermark": watermark} if watermark else {}
        response = client.get(f"{DIRECT_LINE_BASE_URL}/conversations/{conversation_id}/activities", params=params)
        response.raise_for_status()
        payload = response.json()
        watermark = payload.get("watermark") or watermark

        for activity in payload.get("activities", []):
            if activity.get("type") != "message":
                continue
            if (activity.get("from") or {}).get("id") == USER_ID:
                continue
            text = (activity.get("text") or "").strip()
            if text:
                return text

        time.sleep(POLL_INTERVAL_SECONDS)
    return None


def test_teams_round_trip():
    env = require_env("E2E_TEAMS_DIRECTLINE_SECRET")
    nonce = uuid.uuid4().hex[:8]
    prompt = f"E2E integration test {nonce}: what is 2 + 2?"

    headers = {"Authorization": f"Bearer {env['E2E_TEAMS_DIRECTLINE_SECRET']}"}
    with httpx.Client(headers=headers, timeout=30.0) as client:
        conversation_id = _start_conversation(client)
        _send(client, conversation_id, prompt)
        reply = _await_reply(client, conversation_id)

    assert reply is not None, f"No reply from the Teams bot within {REPLY_TIMEOUT_SECONDS}s"
    assert reply not in TEAMS_ERROR_FALLBACKS, f"Bot replied with an error fallback: {reply!r}"
