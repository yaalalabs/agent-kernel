"""End-to-end test for the Instagram integration.

Same ceiling as Messenger: the Instagram Messaging API has no way for one party to send a
DM *as a user* to a business account programmatically — only a real human DMing the
account triggers an inbound webhook. So this can never be automated; it exists as a
harness for manual verification. A human DMs the bot's Instagram business account, then
this test confirms via the deployment's CloudWatch logs that the handler received the
message, ran the agent, and sent a reply.

Manual run (after a human has just DM'd the bot IG account):
    E2E_INSTAGRAM_AUTOMATED=1 uv run pytest test_instagram.py -v

Required when opted in:
- AWS credentials with CloudWatch Logs read access (present in CI, and locally via your
  AWS profile).
Optional:
- E2E_INSTAGRAM_LOOKBACK_SECONDS: how far back to scan for a successful send (default 300).
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


def test_instagram_manual_verification():
    # Opt-in only: Instagram inbound cannot be automated (no user->account DM send API),
    # so this never runs unattended in CI. When enabled it checks the logs for a
    # human-triggered round trip that must have happened in the recent window.
    if not os.environ.get("E2E_INSTAGRAM_AUTOMATED"):
        pytest.skip("Instagram cannot be automated (no API to DM an account as a user); manual verification only")

    import boto3

    lookback = int(os.environ.get("E2E_INSTAGRAM_LOOKBACK_SECONDS", "300"))
    logs = boto3.client("logs", region_name=AWS_REGION)
    start_ms = int((time.time() - lookback) * 1000)

    # Both terms must appear on the line — scopes the match to the Instagram handler's own
    # send-success line (Messenger/WhatsApp log an identical "Message sent successfully").
    sends = _filter_events(logs, start_ms, '"ak.api.instagram" "Message sent successfully"')
    assert sends, (
        f"No successful Instagram send in the last {lookback}s — have a human DM the bot IG account first, "
        f"then re-run. (log group: {LOG_GROUP})"
    )

    errors = _filter_events(logs, start_ms, '"ak.api.instagram" "Error handling message"')
    assert not errors, f"Instagram handler logged an agent-run error: {errors[0]['message'][:300]}"
