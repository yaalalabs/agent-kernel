"""One-time interactive login for the Telegram tester user account.

Prompts for the phone number and login code, then prints a Telethon StringSession to
export as E2E_TELEGRAM_SESSION. Run from e2e/tests:

    uv run python scripts/telegram_login.py

Requires E2E_TELEGRAM_API_ID and E2E_TELEGRAM_API_HASH (from https://my.telegram.org) in
the environment, or enter them at the prompt.
"""

import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(os.environ.get("E2E_TELEGRAM_API_ID") or input("API ID (from my.telegram.org): "))
    api_hash = os.environ.get("E2E_TELEGRAM_API_HASH") or input("API hash (from my.telegram.org): ")

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        print(f"\nLogged in as {me.first_name} (@{me.username})")
        print("\nExport this as E2E_TELEGRAM_SESSION (keep it secret — it grants full account access):\n")
        print(client.session.save())


if __name__ == "__main__":
    asyncio.run(main())
