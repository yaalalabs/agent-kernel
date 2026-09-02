"""Explicit operator action: register this deployment's Telegram webhook."""

import asyncio
import os

import httpx
from dotenv import load_dotenv


async def main():
    load_dotenv()
    token = os.getenv("AK_TELEGRAM__BOT_TOKEN", "")
    secret = os.getenv("AK_TELEGRAM__WEBHOOK_SECRET", "")
    base = os.getenv("SCOPEWISE_PUBLIC_URL", "").rstrip("/")
    if not token or len(secret) < 24 or not base.startswith("https://"):
        raise SystemExit("Configure bot token, a random webhook secret (24+ characters), and an HTTPS public URL first.")
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json={"url": base + "/telegram/webhook", "secret_token": secret, "allowed_updates": ["message"]},
            )
            response.raise_for_status()
            if not response.json().get("ok"):
                raise ValueError("Telegram rejected the webhook.")
    except Exception:
        raise SystemExit("Webhook registration failed. Check credentials and connectivity; no secrets were printed.") from None
    print("Webhook registered. Connect your private chat with a single-use code from the web workspace.")


if __name__ == "__main__":
    asyncio.run(main())
