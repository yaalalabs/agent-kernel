import base64
import hashlib
import hmac
import logging
import traceback
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from ...api import RESTRequestHandler
from ...core import AgentService, Config
from ...core.model import AgentRequestFile, AgentRequestImage, AgentRequestText


class AgentWhatsAppRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with WhatsApp Business API using Agent Kernel.

    This handler uses WhatsApp Cloud API webhooks to receive messages and send responses.

    Endpoints:
    - GET /health: Health check
    - GET /whatsapp/webhook: Webhook verification (required by WhatsApp)
    - POST /whatsapp/webhook: Handle incoming WhatsApp messages
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.whatsapp")
        self._whatsapp_agent = Config.get().whatsapp.agent if Config.get().whatsapp.agent != "" else None
        self._whatsapp_agent_acknowledgement = (
            Config.get().whatsapp.agent_acknowledgement if Config.get().whatsapp.agent_acknowledgement != "" else None
        )
        self._verify_token = Config.get().whatsapp.verify_token
        self._access_token = Config.get().whatsapp.access_token
        self._app_secret = Config.get().whatsapp.app_secret
        self._phone_number_id = Config.get().whatsapp.phone_number_id
        self._api_version = Config.get().whatsapp.api_version or "v24.0"
        self._base_url = f"https://graph.facebook.com/{self._api_version}"
        self._max_file_size = Config.get().api.max_file_size
        if not all([self._access_token, self._phone_number_id, self._verify_token]):
            self._log.error("WhatsApp configuration is incomplete. Please set access_token, phone_number_id, and verify_token.")
            raise ValueError("Incomplete WhatsApp configuration.")

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/whatsapp/webhook")
        async def verify_webhook(request: Request):
            """
            Webhook verification endpoint for WhatsApp.
            WhatsApp will send a GET request with hub.mode, hub.verify_token, and hub.challenge.
            """
            return await self._verify_webhook(request)

        @router.post("/whatsapp/webhook")
        async def handle_webhook(request: Request):
            """
            Handle incoming WhatsApp webhook events.
            """
            return await self._handle_webhook(request)

        return router

    async def _verify_webhook(self, request: Request):
        """
        Verify the webhook with WhatsApp.

        :param request: FastAPI Request object
        :return: The challenge string or error
        """
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        self._log.debug(f"Webhook verification request: mode={mode}, token={token}, challenge={challenge}")

        if mode == "subscribe" and token == self._verify_token and challenge:
            self._log.info("Webhook verified successfully")
            return int(challenge)
        else:
            self._log.warning("Webhook verification failed")
            raise HTTPException(status_code=403, detail="Verification failed")

    async def _handle_webhook(self, request: Request):
        """
        Handle incoming WhatsApp messages.

        :param request: FastAPI Request object
        :return: Success response
        """
        # Verify request signature if app secret is configured
        if self._app_secret:
            signature = request.headers.get("x-hub-signature-256", "")
            if not self._verify_signature(await request.body(), signature):
                self._log.warning("Invalid request signature")
                raise HTTPException(status_code=403, detail="Invalid signature")

        # Process the webhook payload
        try:
            body = await request.json()
            self._log.debug(f"Received WhatsApp webhook: {body}")
            if body.get("object") == "whatsapp_business_account":
                for entry in body.get("entry", []):
                    for change in entry.get("changes", []):
                        value = change.get("value", {})

                        # Check if there are messages
                        if "messages" in value:
                            for message in value["messages"]:
                                await self._handle_message(message, value)

                        # Check for status updates (message delivery, read receipts, etc.)
                        if "statuses" in value:
                            for status in value["statuses"]:
                                self._log.debug(f"Message status update: {status}")

        except Exception as e:
            self._log.error(f"Error processing webhook: {e}\n{traceback.format_exc()}")

        return {"status": "ok"}  # always reply with 200 to avoid automatic retries with erroneous messages

    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify the webhook signature from WhatsApp.

        :param payload: Raw request body
        :param signature: X-Hub-Signature-256 header value
        :return: True if signature is valid
        """
        if not signature.startswith("sha256="):
            return False

        expected_signature = hmac.new(self._app_secret.encode(), payload, hashlib.sha256).hexdigest()

        received_signature = signature[7:]  # Remove 'sha256=' prefix
        return hmac.compare_digest(expected_signature, received_signature)

    async def _handle_message(self, message: dict, value: dict):
        """
        Handle an individual WhatsApp message.

        :param message: Message object from webhook
        :param value: Value object containing metadata
        """
        message_id = message.get("id")
        from_number = message.get("from")
        message_type = message.get("type")

        if not from_number or not message_id:
            self._log.warning("Message missing required fields (from/id)")
            return

        self._log.debug(f"Processing message {message_id} from {from_number} of type {message_type}")

        # Build list of requests to send to agent
        requests = []

        # Extract message text based on type
        text = None
        if message_type == "text":
            text = message.get("text", {}).get("body")
        elif message_type == "interactive":
            # Handle button/list replies
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                text = interactive.get("button_reply", {}).get("title")
            elif interactive.get("type") == "list_reply":
                text = interactive.get("list_reply", {}).get("title")
        elif message_type == "image":
            # Handle image messages
            image_info = message.get("image", {})
            caption = image_info.get("caption", "")
            text = caption if caption else "[Image received]"

            # Download and process the image
            media_id = image_info.get("id")
            if media_id:
                # Get media info to check file size
                media_size, media_mime_type = await self._get_media_info(media_id)
                if media_size is None:
                    await self._send_message(from_number, "Sorry, I could not retrieve the image information. Please try again.", message_id)
                    return

                # Check file size
                if media_size > self._max_file_size:
                    await self._send_message(
                        from_number,
                        f"Sorry, the image file size ({media_size / (1024 * 1024):.2f} MB) exceeds the maximum allowed size of {self._max_file_size / (1024 * 1024):.2f} MB.",
                        message_id,
                    )
                    return

                # Download the media
                image_data = await self._download_media(media_id)
                if image_data is None:
                    await self._send_message(from_number, "Sorry, I could not download the image. Please try again.", message_id)
                    return

                requests.append(
                    AgentRequestImage(
                        image_data=image_data,
                        name=f"whatsapp_image_{message_id}",
                        mime_type=media_mime_type or image_info.get("mime_type", "image/jpeg"),
                    )
                )
                self._log.info(f"Image downloaded and added to request")

        elif message_type == "document":
            # Handle document messages
            document_info = message.get("document", {})
            caption = document_info.get("caption", "")
            filename = document_info.get("filename", "document")
            text = caption if caption else f"[Document received: {filename}]"

            # Download and process the document
            media_id = document_info.get("id")
            if media_id:
                # Get media info to check file size
                media_size, media_mime_type = await self._get_media_info(media_id)
                if media_size is None:
                    await self._send_message(
                        from_number,
                        f"Sorry, I could not retrieve the document '{filename}' information. Please try again.",
                        message_id,
                    )
                    return

                # Check file size
                if media_size > self._max_file_size:
                    await self._send_message(
                        from_number,
                        f"Sorry, the document '{filename}' size ({media_size / (1024 * 1024):.2f} MB) exceeds the maximum allowed size of {self._max_file_size / (1024 * 1024):.2f} MB.",
                        message_id,
                    )
                    return

                # Download the media
                file_data = await self._download_media(media_id)
                if file_data is None:
                    await self._send_message(
                        from_number,
                        f"Sorry, I could not download the document '{filename}'. Please try again.",
                        message_id,
                    )
                    return

                requests.append(
                    AgentRequestFile(
                        file_data=file_data,
                        name=filename,
                        mime_type=media_mime_type or document_info.get("mime_type"),
                    )
                )
                self._log.info(f"Document '{filename}' downloaded and added to request")

        elif message_type in ["video", "audio"]:
            # cannot handle these types yet
            await self._send_message(from_number, "Sorry, audio and video messages are not supported yet.", message_id)
            return

        if not text:
            self._log.warning(f"Unsupported message type: {message_type}")
            return

        # Add text as the first request
        requests.insert(0, AgentRequestText(text=text))

        # Use from_number as session_id to maintain conversation context
        session_id = from_number

        service = AgentService()
        try:
            # Send acknowledgement if configured
            if self._whatsapp_agent_acknowledgement:
                await self._send_message(from_number, self._whatsapp_agent_acknowledgement, message_id)

            # Select and run agent
            service.select(session_id=session_id, name=self._whatsapp_agent)
            if not service.agent:
                await self._send_message(from_number, "Sorry, no agent is available to handle your request.", message_id)
                return

            # Run the agent with all requests (text + media)
            result = await service.run_multi(requests=requests)

            response_text = str(result)

            self._log.debug(f"Agent response: {response_text}")

            # Send the response
            await self._send_message(from_number, response_text, message_id)

        except Exception as e:
            self._log.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            await self._send_message(from_number, "Sorry, there was an error processing your request.", message_id)

    async def _send_message(self, to_number: str, text: str, reply_to_message_id: Optional[str] = None):
        """
        Send a WhatsApp message using the Cloud API.

        :param to_number: Recipient phone number
        :param text: Message text
        :param reply_to_message_id: Optional message ID to reply to
        """
        url = f"{self._base_url}/{self._phone_number_id}/messages"

        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

        # Split message if it exceeds WhatsApp's limit (4096 characters)
        max_length = 4096
        messages = [text[i : i + max_length] for i in range(0, len(text), max_length)]

        async with httpx.AsyncClient() as client:
            for i, message_text in enumerate(messages):
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to_number,
                    "type": "text",
                    "text": {"body": message_text},
                }

                # Only add context for the first message
                if i == 0 and reply_to_message_id:
                    payload["context"] = {"message_id": reply_to_message_id}

                try:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    self._log.debug(f"Message sent successfully: {response.json()}")

                    if len(messages) > 1 and i < len(messages) - 1:
                        self._log.info(f"Sent part {i+1}/{len(messages)} of split message")

                except httpx.HTTPStatusError as e:
                    self._log.error(f"Failed to send message: {e.response.text}")
                    raise
                except Exception as e:
                    self._log.error(f"Error sending message: {e}")
                    raise

    async def _get_media_info(self, media_id: str) -> tuple[Optional[int], Optional[str]]:
        """
        Get media file information from WhatsApp (size and mime type).

        :param media_id: WhatsApp media ID
        :return: Tuple of (file_size_in_bytes, mime_type) or (None, None) if failed
        """
        try:
            url = f"{self._base_url}/{media_id}"
            headers = {"Authorization": f"Bearer {self._access_token}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                media_info = response.json()

                file_size = media_info.get("file_size")
                mime_type = media_info.get("mime_type")

                if file_size is None:
                    self._log.error(f"No file size found for media ID {media_id}")
                    return None, None

                return int(file_size), mime_type

        except httpx.HTTPStatusError as e:
            self._log.error(f"HTTP error getting media info {media_id}: {e.response.text}")
            return None, None
        except Exception as e:
            self._log.error(f"Error getting media info {media_id}: {e}\n{traceback.format_exc()}")
            return None, None

    async def _download_media(self, media_id: str) -> Optional[str]:
        """
        Download media file from WhatsApp and return as base64 encoded string.

        :param media_id: WhatsApp media ID
        :return: Base64 encoded media data or None if download fails
        """
        try:
            # Step 1: Get media URL
            url = f"{self._base_url}/{media_id}"
            headers = {"Authorization": f"Bearer {self._access_token}"}

            async with httpx.AsyncClient() as client:
                # Get media metadata
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                media_info = response.json()

                media_url = media_info.get("url")
                if not media_url:
                    self._log.error(f"No URL found for media ID {media_id}")
                    return None

                # Step 2: Download the actual media file
                self._log.debug(f"Downloading media from {media_url}")
                media_response = await client.get(media_url, headers=headers)
                media_response.raise_for_status()

                # Step 3: Encode to base64
                media_bytes = media_response.content
                base64_encoded = base64.b64encode(media_bytes).decode("utf-8")

                self._log.debug(f"Media downloaded successfully, size: {len(media_bytes)} bytes")
                return base64_encoded

        except httpx.HTTPStatusError as e:
            self._log.error(f"HTTP error downloading media {media_id}: {e.response.text}")
            return None
        except Exception as e:
            self._log.error(f"Error downloading media {media_id}: {e}\n{traceback.format_exc()}")
            return None

    async def _mark_message_as_read(self, message_id: str):
        """
        Mark a message as read.

        :param message_id: ID of the message to mark as read
        """
        url = f"{self._base_url}/{self._phone_number_id}/messages"

        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                self._log.debug(f"Message marked as read: {message_id}")
        except Exception as e:
            self._log.warning(f"Failed to mark message as read: {e}")
