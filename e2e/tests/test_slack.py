"""End-to-end test for the Slack integration.

Sends a real message into the test channel as a human user (Slack user token) and waits
for the deployed agent's threaded reply. The message must be sent with a *user* token
(xoxp-): the Slack handler reads ``body["user"]`` from the message event, which is absent
on bot-authored messages, so a second bot cannot act as the sender.

Required environment variables:
- E2E_SLACK_USER_TOKEN: user OAuth token (xoxp-) of the tester account.
  Scopes: chat:write, channels:history.
- E2E_SLACK_CHANNEL_ID: channel the deployed bot is a member of.
- SLACK_BOT_TOKEN (xoxb-) or E2E_SLACK_BOT_USER_ID: used to identify which thread
  replies came from the deployed bot.
"""

import os
import time
import uuid

import pytest
from conftest import POLL_INTERVAL_SECONDS, REPLY_TIMEOUT_SECONDS, require_env
from slack_sdk import WebClient

# Fallback the handler posts when the agent run fails; a reply matching this means the
# transport worked but the agent errored, which must still fail the test.
SLACK_ERROR_FALLBACK = "Error handling your request."


def _bot_user_id() -> str:
    bot_user_id = os.environ.get("E2E_SLACK_BOT_USER_ID")
    if bot_user_id:
        return bot_user_id
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        pytest.skip("Set SLACK_BOT_TOKEN or E2E_SLACK_BOT_USER_ID to identify the bot's replies")
    return WebClient(token=bot_token).auth_test()["user_id"]


def _message_text(message: dict) -> str:
    """Extract the visible text of a Slack message, preferring section blocks."""
    parts = []
    for block in message.get("blocks") or []:
        if block.get("type") == "section":
            parts.append(block.get("text", {}).get("text", ""))
    return "\n".join(parts).strip() or message.get("text", "").strip()


def test_slack_round_trip():
    env = require_env("E2E_SLACK_USER_TOKEN", "E2E_SLACK_CHANNEL_ID")
    channel = env["E2E_SLACK_CHANNEL_ID"]
    user_client = WebClient(token=env["E2E_SLACK_USER_TOKEN"])
    bot_user_id = _bot_user_id()

    nonce = uuid.uuid4().hex[:8]
    sent = user_client.chat_postMessage(channel=channel, text=f"E2E integration test {nonce}: what is 2 + 2?")
    parent_ts = sent["ts"]

    reply = None
    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        replies = user_client.conversations_replies(channel=channel, ts=parent_ts)
        bot_replies = [m for m in replies["messages"] if m.get("user") == bot_user_id and m["ts"] != parent_ts]
        if bot_replies:
            reply = bot_replies[-1]
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    assert reply is not None, f"No reply from bot {bot_user_id} in thread {parent_ts} within {REPLY_TIMEOUT_SECONDS}s"
    reply_text = _message_text(reply)
    assert reply_text, f"Bot reply has no visible text: {reply}"
    assert reply_text != SLACK_ERROR_FALLBACK, "Bot replied with its error fallback — the agent run failed"
