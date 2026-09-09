"""End-to-end test for the WhatsApp integration.

Sends a real inbound message to the bot's WhatsApp business number using a SECOND
business number (in a separate Meta app — the handler replies to every message the app's
webhook delivers, so a shared app would loop on its own replies). Business-initiated
messages must be pre-approved templates, so the sender uses the built-in ``hello_world``
template; it arrives at the bot as a normal inbound text webhook.

Verification ceiling (unlike Slack/Telegram/Gmail): WhatsApp has no API to read the
sender number's inbox, so the reply cannot be read back. Instead the test polls the
deployment's CloudWatch logs for the handler's send-success line (which echoes the Graph
API response containing the recipient's wa_id) and fails if the handler logged an
agent-run error. This proves inbound webhook → agent run → Graph API accepted the reply.

Required environment variables:
- E2E_WHATSAPP_SENDER_ACCESS_TOKEN: Cloud API token of the SENDER Meta app.
- E2E_WHATSAPP_SENDER_PHONE_NUMBER_ID: phone number ID of the sender number.
- E2E_WHATSAPP_BOT_NUMBER: the bot's number in international format (digits, no +).
- E2E_WHATSAPP_SENDER_NUMBER: the sender's number (digits, no +) — matched against the
  wa_id in the bot's send-success log line.
AWS credentials with CloudWatch Logs read access must be available (they are in CI).
"""

import os
import time

import httpx
import pytest

from conftest import POLL_INTERVAL_SECONDS, REPLY_TIMEOUT_SECONDS, require_env

LOG_GROUP = os.environ.get("E2E_LOG_GROUP", "/aws/ecs/ak-e2e-dev-messaging-service/ak-e2e-dev-messaging-app")
AWS_REGION = os.environ.get("E2E_AWS_REGION", "us-east-2")
GRAPH_API_VERSION = "v24.0"


def _filter_events(logs, start_ms: int, pattern: str) -> list[dict]:
    events = []
    kwargs = {"logGroupName": LOG_GROUP, "startTime": start_ms, "filterPattern": pattern}
    while True:
        page = logs.filter_log_events(**kwargs)
        events.extend(page.get("events", []))
        if "nextToken" not in page:
            return events
        kwargs["nextToken"] = page["nextToken"]


def test_whatsapp_round_trip():
    # Opt-in only. WhatsApp Cloud API *test* numbers cannot message each other: the bot
    # number can't be verified into the sender's allowed-recipient list (the verification
    # OTP is undeliverable to a test number), so an automated sender->bot send always
    # returns error 131030. Fully automating this test therefore requires a *production*
    # sender number (business-verified + payment method). Until one exists the test skips;
    # the deployment/handler are verified manually (see e2e/README.md). Set
    # E2E_WHATSAPP_AUTOMATED=1 once a production sender is available.
    if not os.environ.get("E2E_WHATSAPP_AUTOMATED"):
        pytest.skip("WhatsApp automated test needs a production sender number (test numbers can't message each other)")

    env = require_env(
        "E2E_WHATSAPP_SENDER_ACCESS_TOKEN",
        "E2E_WHATSAPP_SENDER_PHONE_NUMBER_ID",
        "E2E_WHATSAPP_BOT_NUMBER",
        "E2E_WHATSAPP_SENDER_NUMBER",
    )
    import boto3

    logs = boto3.client("logs", region_name=AWS_REGION)
    start_ms = int(time.time() * 1000)

    # Business-initiated message: must be a template (hello_world is pre-approved).
    response = httpx.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{env['E2E_WHATSAPP_SENDER_PHONE_NUMBER_ID']}/messages",
        headers={"Authorization": f"Bearer {env['E2E_WHATSAPP_SENDER_ACCESS_TOKEN']}"},
        json={
            "messaging_product": "whatsapp",
            "to": env["E2E_WHATSAPP_BOT_NUMBER"],
            "type": "template",
            "template": {"name": "hello_world", "language": {"code": "en_US"}},
        },
        timeout=30.0,
    )
    assert response.status_code == 200, f"Sender Graph API call failed: {response.status_code} {response.text}"

    sender_wa_id = env["E2E_WHATSAPP_SENDER_NUMBER"].lstrip("+")
    reply_event = None
    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        events = _filter_events(logs, start_ms, '"Message sent successfully"')
        matches = [e for e in events if sender_wa_id in e["message"]]
        if matches:
            reply_event = matches[-1]
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    assert reply_event is not None, (
        f"No send-success log entry for wa_id {sender_wa_id} within {REPLY_TIMEOUT_SECONDS}s — "
        f"the bot never replied (check the webhook registration and {LOG_GROUP})"
    )

    # The error fallback also sends (and logs) successfully — catch it via the error log
    # the handler writes just before falling back.
    errors = _filter_events(logs, start_ms, '"Error handling message"')
    assert (
        not errors
    ), f"Handler logged an agent-run error — the reply was the error fallback: {errors[0]['message'][:300]}"
