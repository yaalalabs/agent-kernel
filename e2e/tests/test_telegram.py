"""End-to-end test for the Telegram integration.

Sends a real message to the deployed bot from a real Telegram *user* account (bots cannot
message other bots) using Telethon/MTProto, then waits for the bot's reply in the same
chat.

Required environment variables:
- E2E_TELEGRAM_API_ID / E2E_TELEGRAM_API_HASH: MTProto app credentials from
  https://my.telegram.org (API development tools).
- E2E_TELEGRAM_SESSION: Telethon StringSession of the tester user account. Generate it
  once with scripts/telegram_login.py.
- E2E_TELEGRAM_BOT_USERNAME: username of the deployed bot (e.g. @ak_e2e_bot).
"""

import asyncio
import time
import uuid

from conftest import POLL_INTERVAL_SECONDS, REPLY_TIMEOUT_SECONDS, require_env
from telethon import TelegramClient
from telethon.sessions import StringSession

# Fallbacks the handler sends when the agent run fails or no agent matches; a reply
# matching one of these means the transport worked but the agent errored.
TELEGRAM_ERROR_FALLBACKS = {
    "Sorry, there was an error processing your request.",
    "Sorry, no agent is available to handle your request.",
    "Sorry, your message appears to be empty.",
}


async def _round_trip(api_id: int, api_hash: str, session: str, bot_username: str, prompt: str) -> str | None:
    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        bot = await client.get_entity(bot_username)
        sent = await client.send_message(bot, prompt)

        deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            messages = await client.get_messages(bot, min_id=sent.id, limit=20)
            incoming = [m for m in messages if not m.out and (m.text or "").strip()]
            if incoming:
                # get_messages returns newest first; take the earliest reply after ours.
                return incoming[-1].text.strip()
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    return None


def test_telegram_round_trip():
    env = require_env(
        "E2E_TELEGRAM_API_ID", "E2E_TELEGRAM_API_HASH", "E2E_TELEGRAM_SESSION", "E2E_TELEGRAM_BOT_USERNAME"
    )
    nonce = uuid.uuid4().hex[:8]
    prompt = f"E2E integration test {nonce}: what is 2 + 2?"

    reply = asyncio.run(
        _round_trip(
            api_id=int(env["E2E_TELEGRAM_API_ID"]),
            api_hash=env["E2E_TELEGRAM_API_HASH"],
            session=env["E2E_TELEGRAM_SESSION"],
            bot_username=env["E2E_TELEGRAM_BOT_USERNAME"],
            prompt=prompt,
        )
    )

    assert reply is not None, f"No reply from {env['E2E_TELEGRAM_BOT_USERNAME']} within {REPLY_TIMEOUT_SECONDS}s"
    assert reply not in TELEGRAM_ERROR_FALLBACKS, f"Bot replied with an error fallback: {reply!r}"
