"""Graph API signaling for WhatsApp Business Calling.

One thin async client; every method returns True/False and logs failures — the
call state machine treats a failed signal as a terminal event, never an exception.
Payload shapes follow the Cloud API Calling docs (v24.0): POST
``/{phone_number_id}/calls`` with ``action`` + optional SDP ``session``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("sarasavi.voice.calls_api")


class WhatsAppCallsAPI:
    def __init__(self, base_url: str, phone_number_id: str, access_token: str):
        self._url = f"{base_url}/{phone_number_id}/calls"
        self._settings_url = f"{base_url}/{phone_number_id}/settings"
        self._headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    async def _post(self, url: str, payload: dict[str, Any], label: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, headers=self._headers, json=payload)
                if response.status_code >= 400:
                    logger.error("%s failed: HTTP %s %s", label, response.status_code, response.text[:500])
                    return False
                return True
        except Exception:
            logger.exception("%s failed", label)
            return False

    async def _call_action(self, call_id: str, action: str, sdp: str | None = None) -> bool:
        payload: dict[str, Any] = {"messaging_product": "whatsapp", "call_id": call_id, "action": action}
        if sdp is not None:
            payload["session"] = {"sdp_type": "answer", "sdp": sdp}
        return await self._post(self._url, payload, f"calls/{action}")

    async def pre_accept(self, call_id: str, sdp: str) -> bool:
        return await self._call_action(call_id, "pre_accept", sdp)

    async def accept(self, call_id: str, sdp: str) -> bool:
        return await self._call_action(call_id, "accept", sdp)

    async def reject(self, call_id: str) -> bool:
        return await self._call_action(call_id, "reject")

    async def terminate(self, call_id: str) -> bool:
        return await self._call_action(call_id, "terminate")

    async def enable_calling(self) -> bool:
        """One-time per number; safe to repeat. Run via scripts or on demand.

        Sets the three fields explicitly. ``status`` alone leaves a freshly added
        number with ``call_icon_visibility: NOT_SET``, and without the call icon
        users have no way to dial the business at all.
        """
        payload = {
            "calling": {
                "status": "ENABLED",
                "call_icon_visibility": "DEFAULT",  # show the call button in the chat
                "callback_permission_status": "ENABLED",  # let users grant call permission
            }
        }
        return await self._post(self._settings_url, payload, "settings/enable_calling")

    async def read_settings(self) -> dict:
        """Read back the number's calling settings.

        Enabling can succeed while the number is still not dialable, so the
        authoritative check is what Meta reports afterwards — chiefly
        ``calling.status`` and ``calling.callback_permission_status``.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.get(self._settings_url, headers=self._headers)
                if response.status_code >= 400:
                    logger.error("settings read failed: HTTP %s %s", response.status_code, response.text)
                    return {}
                return response.json().get("calling", {})
            except httpx.HTTPError:
                logger.exception("settings read failed")
                return {}
