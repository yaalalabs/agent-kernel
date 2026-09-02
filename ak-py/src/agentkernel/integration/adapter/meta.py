"""Webhook verification shared by the three Meta platforms.

WhatsApp, Messenger and Instagram all sit behind the same Graph webhook contract: a
``hub.challenge`` handshake on GET, and an ``X-Hub-Signature-256`` HMAC on every POST. The three
adapters differ in what they parse, not in how they authenticate, so that part lives here once.
"""

import base64
import hashlib
import hmac
import logging
from typing import List, Optional, Tuple

import httpx
from fastapi import HTTPException, Request

_log = logging.getLogger("ak.integration.meta")


async def verify_signature(request: Request, app_secret: Optional[str]) -> None:
    """Reject a delivery whose HMAC does not match the app secret.

    No app secret configured means no check, which is the behaviour these integrations have
    always had: the secret is optional in the platform config.

    :param request: The incoming webhook request.
    :param app_secret: The app secret from the platform's config block.
    :raises HTTPException: 403 when a secret is configured and the signature does not match.
    """
    if not app_secret:
        return
    signature = request.headers.get("x-hub-signature-256", "")
    if not signature.startswith("sha256="):
        _log.warning("Invalid request signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    expected = hmac.new(app_secret.encode(), await request.body(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature[len("sha256=") :]):
        _log.warning("Invalid request signature")
        raise HTTPException(status_code=403, detail="Invalid signature")


async def answer_challenge(request: Request, verify_token: Optional[str]) -> int:
    """Answer Meta's subscription handshake by echoing its challenge.

    :param request: The incoming GET request carrying hub.mode, hub.verify_token, hub.challenge.
    :param verify_token: The token from the platform's config block.
    :return: The challenge, echoed back as an integer, which is what Meta expects.
    :raises HTTPException: 403 when the mode or token does not match.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == verify_token and challenge:
        _log.info("Webhook verified successfully")
        return int(challenge)

    _log.warning("Webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


class MetaSendAPIClient:
    """The Send API calls Messenger and Instagram share.

    Both post to ``/me/messages`` on their own Graph host with a page/business access token; the
    only difference is Messenger's ``messaging_type`` field.
    """

    def __init__(self, base_url: str, access_token: str, message_fields: Optional[dict] = None, log: Optional[logging.Logger] = None):
        """
        :param base_url: The platform's Graph base URL.
        :param access_token: Page (Messenger) or business (Instagram) access token.
        :param message_fields: Extra top-level fields to include on every send.
        :param log: Logger the owning adapter reports on.
        """
        self._url = f"{base_url}/me/messages"
        self._access_token = access_token
        self._message_fields = message_fields or {}
        self._log = log or _log

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

    async def send_message(self, recipient_id: str, chunks: List[str]) -> None:
        """Send each chunk as its own message, in order."""
        async with httpx.AsyncClient() as client:
            for chunk in chunks:
                payload = {"recipient": {"id": recipient_id}, "message": {"text": chunk}, **self._message_fields}
                response = await client.post(self._url, json=payload, headers=self._headers())
                response.raise_for_status()
                self._log.debug(f"Message sent successfully: {response.json()}")

    async def sender_action(self, recipient_id: str, action: str) -> None:
        """Send a typing indicator or read receipt. Never raises: these are courtesies."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._url,
                    json={"recipient": {"id": recipient_id}, "sender_action": action},
                    headers=self._headers(),
                )
                response.raise_for_status()
                self._log.debug(f"Sender action '{action}' sent to {recipient_id}")
        except Exception as e:
            self._log.warning(f"Failed to send sender action '{action}': {e}")

    async def download_attachment(self, url: str, max_file_size: int) -> Optional[Tuple[str, str, str]]:
        """Download one attachment by URL.

        :return: (base64 data, file name, MIME type), or None when it is missing or too large.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            content = response.content

        if len(content) > max_file_size:
            self._log.warning(
                f"Attachment size ({len(content) / (1024 * 1024):.2f} MB) exceeds maximum allowed size of {max_file_size / (1024 * 1024):.2f} MB"
            )
            return None

        mime_type = response.headers.get("content-type", "application/octet-stream")
        filename = url.split("/")[-1].split("?")[0] or "attachment"
        return base64.b64encode(content).decode("utf-8"), filename, mime_type
