"""End-to-end test for the Facebook Messenger integration.

Verification ceiling — stronger than WhatsApp's: the Messenger Platform has **no** API
for one party to send a message *as a user to a Page*. The only way to deliver an inbound
message to the bot Page is a real human typing in Messenger. So — unlike WhatsApp, where a
production sender number would unlock automation — Messenger's inbound leg can NEVER be
driven programmatically. This test therefore always skips in CI and exists only as a
harness for the manual verification flow: a human DMs the Page, then this test confirms
via the deployment's CloudWatch logs that the handler received the message, ran the agent,
and sent a reply.

Manual run (after a human has just DM'd the bot Page):
    E2E_MESSENGER_AUTOMATED=1 uv run pytest test_messenger.py -v

Required when opted in:
- AWS credentials with CloudWatch Logs read access (present in CI, and locally via your
  AWS profile).
Optional:
- E2E_MESSENGER_LOOKBACK_SECONDS: how far back to scan for a successful send (default 300).
"""

import os
import time

import pytest

LOG_GROUP = os.environ.get("E2E_LOG_GROUP", "/aws/ecs/ak-e2e-dev-messaging-service/ak-e2e-dev-messaging-app")
AWS_REGION = os.environ.get("E2E_AWS_REGION", "us-east-2")


def _filter_events(logs, start_ms: int, pattern: str) -> list[dict]:
    events = []
    kwargs = {"logGroupName": LOG_GROUP, "startTime": start_ms, "filterPattern": pattern}
    while True:
        page = logs.filter_log_events(**kwargs)
        events.extend(page.get("events", []))
        if "nextToken" not in page:
            return events
        kwargs["nextToken"] = page["nextToken"]


def test_messenger_manual_verification():
    # Opt-in only: Messenger inbound cannot be automated (no user->Page send API), so this
    # never runs unattended in CI. When enabled it checks the logs for a human-triggered
    # round trip that must have happened in the recent window.
    if not os.environ.get("E2E_MESSENGER_AUTOMATED"):
        pytest.skip("Messenger cannot be automated (no API to message a Page as a user); manual verification only")

    import boto3

    lookback = int(os.environ.get("E2E_MESSENGER_LOOKBACK_SECONDS", "300"))
    logs = boto3.client("logs", region_name=AWS_REGION)
    start_ms = int((time.time() - lookback) * 1000)

    # Both terms must appear on the line — scopes the match to the Messenger handler's own
    # send-success line (the WhatsApp handler logs an identical "Message sent successfully").
    sends = _filter_events(logs, start_ms, '"ak.api.messenger" "Message sent successfully"')
    assert sends, (
        f"No successful Messenger send in the last {lookback}s — have a human DM the bot Page first, "
        f"then re-run. (log group: {LOG_GROUP})"
    )

    errors = _filter_events(logs, start_ms, '"ak.api.messenger" "Error handling message"')
    assert not errors, f"Messenger handler logged an agent-run error: {errors[0]['message'][:300]}"
