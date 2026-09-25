"""One-shot: enable the WhatsApp Business Calling API on the configured number.

Run after filling AK_WHATSAPP__* in .env (safe to repeat):
  uv run python devtools/enable_calling.py

A WABA can host several numbers, so an explicit id can be passed to enable a
newly added one without editing .env first:
  uv run python devtools/enable_calling.py <PHONE_NUMBER_ID>

Also remember, in the Meta app dashboard: subscribe the webhook to the `calls`
field (alongside `messages`), and for sandbox tests have each tester open the
business chat -> Business Calling Permission -> Allow calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from voice.calls_api import WhatsAppCallsAPI


async def main() -> None:
    phone_number_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AK_WHATSAPP__PHONE_NUMBER_ID", "")
    access_token = os.environ.get("AK_WHATSAPP__ACCESS_TOKEN", "")
    api_version = os.environ.get("AK_WHATSAPP__API_VERSION", "v24.0")
    if not phone_number_id or not access_token:
        raise SystemExit("Set AK_WHATSAPP__PHONE_NUMBER_ID and AK_WHATSAPP__ACCESS_TOKEN in .env first.")

    base = f"https://graph.facebook.com/{api_version}"
    api = WhatsAppCallsAPI(base, phone_number_id, access_token)
    ok = await api.enable_calling()
    if not ok:
        raise SystemExit("Failed — see the log above (token/permissions/number id?).")

    print(f"Calling ENABLED on {phone_number_id}.")
    # Read the settings back: enabling is silent on partial failures, and
    # callback_permission_status is what actually lets users dial in.
    status = await api.read_settings()
    print("Current settings:", status)


if __name__ == "__main__":
    asyncio.run(main())
