"""Register the deployed API Gateway endpoint as the Telegram bot's webhook.

Run once after `deploy.sh` (and again only if the gateway URL or secret changes):

    uv run python scripts/set_telegram_webhook.py --url "$(terraform -chdir=../app/deploy output -raw telegram_webhook_url)"

Requires E2E_TELEGRAM_BOT_TOKEN in the environment (same value as the deployment's
telegram_bot_token terraform variable). If E2E_TELEGRAM_WEBHOOK_SECRET is set it is
registered as the webhook secret token and must match the deployment's
telegram_webhook_secret variable.
"""

import argparse
import os
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Public webhook URL (terraform output telegram_webhook_url)")
    args = parser.parse_args()

    bot_token = os.environ.get("E2E_TELEGRAM_BOT_TOKEN")
    if not bot_token:
        sys.exit("E2E_TELEGRAM_BOT_TOKEN is not set")

    payload = {"url": args.url, "drop_pending_updates": True}
    secret = os.environ.get("E2E_TELEGRAM_WEBHOOK_SECRET")
    if secret:
        payload["secret_token"] = secret

    base = f"https://api.telegram.org/bot{bot_token}"
    response = httpx.post(f"{base}/setWebhook", json=payload, timeout=30.0)
    response.raise_for_status()
    print(f"setWebhook: {response.json()}")

    info = httpx.get(f"{base}/getWebhookInfo", timeout=30.0)
    info.raise_for_status()
    print(f"getWebhookInfo: {info.json()}")


if __name__ == "__main__":
    main()
