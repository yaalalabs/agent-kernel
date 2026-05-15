import base64
import hashlib
import hmac
import logging
import traceback

import httpx
from fastapi import APIRouter, HTTPException, Request

from ...api import RESTRequestHandler
from ...core import AgentService, Config
from ...core.model import AgentRequestFile, AgentRequestImage, AgentRequestText


class AgentMessengerRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Facebook Messenger API using Agent Kernel.

    This handler uses Facebook Messenger Platform webhooks to receive messages and send responses.

    Endpoints:
    - GET /health: Health check
    - GET /messenger/webhook: Webhook verification (required by Facebook)
    - POST /messenger/webhook: Handle incoming Messenger messages
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.messenger")
        self._messenger_agent = Config.get().messenger.agent if Config.get().messenger.agent != "" else None
        self._verify_token = Config.get().messenger.verify_token
        self._access_token = Config.get().messenger.access_token
        self._app_secret = Config.get().messenger.app_secret
        self._api_version = Config.get().messenger.api_version or "v24.0"
        self._base_url = f"https://graph.facebook.com/{self._api_version}"
        self._max_file_size = Config.get().api.max_file_size
        if not all([self._access_token, self._verify_token]):
            self._log.error("Facebook Messenger configuration is incomplete. Please set access_token and verify_token.")
            raise ValueError("Incomplete Facebook Messenger configuration.")

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/messenger/webhook")
        async def verify_webhook(request: Request):
            """
            Webhook verification endpoint for Facebook Messenger.
            Facebook will send a GET request with hub.mode, hub.verify_token, and hub.challenge.
            """
            return await self._verify_webhook(request)

        @router.post("/messenger/webhook")
        async def handle_webhook(request: Request):
            """
            Handle incoming Messenger webhook events.
            """
            return await self._handle_webhook(request)

        return router

    async def _verify_webhook(self, request: Request):
        """
        Verify the webhook with Facebook.

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
        Handle incoming Messenger messages.

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
            self._log.debug(f"Received Messenger webhook: {body}")
            if body.get("object") == "page":
                for entry in body.get("entry", []):
                    for messaging_event in entry.get("messaging", []):
                        # Handle different event types
                        if "message" in messaging_event:
                            await self._handle_message(messaging_event)
                        elif "postback" in messaging_event:
                            await self._handle_postback(messaging_event)
                        elif "delivery" in messaging_event:
                            # Message delivery confirmation
                            self._log.debug(f"Message delivery confirmation: {messaging_event['delivery']}")
                        elif "read" in messaging_event:
                            # Message read receipt
                            self._log.debug(f"Message read receipt: {messaging_event['read']}")
        except Exception as e:
            self._log.error(f"Error processing webhook: {e}\n{traceback.format_exc()}")

        return {"status": "ok"}  # always return 200 OK to Facebook to avoid retries with erroneous messages

    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify the webhook signature from Facebook.

        :param payload: Raw request body
        :param signature: X-Hub-Signature-256 header value
        :return: True if signature is valid
        """
        if not signature.startswith("sha256="):
            return False

        expected_signature = hmac.new(self._app_secret.encode(), payload, hashlib.sha256).hexdigest()

        received_signature = signature[7:]  # Remove 'sha256=' prefix
        return hmac.compare_digest(expected_signature, received_signature)

    async def _handle_message(self, messaging_event: dict):
        """
        Handle an individual Messenger message.

        :param messaging_event: Messaging event object from webhook
        """
        sender_id = messaging_event.get("sender", {}).get("id")
        message = messaging_event.get("message", {})
        message_id = message.get("mid")
        message_text = message.get("text", "").strip()
        attachments = message.get("attachments", [])

        if not sender_id or not message_id:
            self._log.warning("Message missing required fields (sender/mid)")
            return

        # Skip if no text and no attachments
        if not message_text and not attachments:
            self._log.warning("Message has no text content or attachments")
            return

        self._log.debug(f"Processing message {message_id} from {sender_id}: text='{message_text}', attachments={len(attachments)}")
        await self._process_agent_message(sender_id, message_text, attachments)

    async def _handle_postback(self, messaging_event: dict):
        """
        Handle a postback event (button clicks, quick replies, etc.).

        :param messaging_event: Messaging event object from webhook
        """
        sender_id = messaging_event.get("sender", {}).get("id")
        postback = messaging_event.get("postback", {})
        payload = postback.get("payload")
        title = postback.get("title")

        if not sender_id:
            self._log.warning("Postback missing sender id")
            return

        self._log.debug(f"Processing postback from {sender_id}: {title} - {payload}")

        # Treat postback title as message text
        message_text = title or payload

        if not message_text:
            self._log.warning("Postback has no title or payload")
            return

        self._log.debug(f"Processing postback from {sender_id}: {message_text}")
        await self._process_agent_message(sender_id, message_text)

    async def _process_agent_message(self, sender_id: str, message_text: str, attachments: list = None):
        service = AgentService()
        session_id = sender_id  # Use sender_id as session_id to maintain conversation context
        try:
            # Mark message as seen
            await self._mark_seen(sender_id)

            # Send typing indicator
            await self._send_typing_indicator(sender_id, True)

            # Select and run agent
            service.select(session_id=session_id, name=self._messenger_agent)
            if not service.agent:
                self._log.warning(f"No agent available for name: {self._messenger_agent} (session_id: {session_id})")
                await self._send_message(sender_id, "Sorry, no agent is available to handle your request.")
                await self._send_typing_indicator(sender_id, False)
                return

            # Build requests list with text and attachments
            requests = []

            # Add text if present
            if message_text:
                requests.append(AgentRequestText(text=message_text))

            # Process attachments (images and files)
            if attachments:
                for attachment in attachments:
                    await self._process_attachment(attachment, requests)

            # Run the agent
            if requests:
                # Use run_multi for multimodal requests
                if len(requests) > 1 or any(isinstance(r, (AgentRequestFile, AgentRequestImage)) for r in requests):
                    result = await service.run_multi(requests=requests)
                else:
                    result = await service.run(message_text) if message_text else None
            else:
                result = None

            if result:
                if hasattr(result, "raw"):
                    response_text = str(result.raw)
                else:
                    response_text = str(result)
            else:
                response_text = "Sorry, I could not process your message."

            self._log.debug(f"Agent response: {response_text}")

            # Turn off typing indicator and send the response
            await self._send_typing_indicator(sender_id, False)
            await self._send_message(sender_id, response_text)

        except Exception as e:
            self._log.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            await self._send_typing_indicator(sender_id, False)
            await self._send_message(sender_id, "Sorry, there was an error processing your request.")

    async def _process_attachment(self, attachment: dict, requests: list):
        """
        Process a Messenger attachment (image or file).

        :param attachment: Attachment object from message
        :param requests: List to append the processed request to
        """
        attachment_type = attachment.get("type")
        payload = attachment.get("payload", {})
        url = payload.get("url")

        if not url:
            self._log.warning(f"Attachment has no URL: {attachment}")
            return

        try:
            # Download the attachment
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                response.raise_for_status()
                file_data = response.content

            # Check file size
            if len(file_data) > self._max_file_size:
                self._log.warning(
                    f"Attachment size ({len(file_data) / (1024 * 1024):.2f} MB) exceeds maximum allowed size of {self._max_file_size / (1024 * 1024):.2f} MB"
                )
                return

            # Encode to base64
            file_data_base64 = base64.b64encode(file_data).decode("utf-8")

            # Get MIME type
            mime_type = response.headers.get("content-type", "application/octet-stream")

            # Extract filename from URL if available
            filename = url.split("/")[-1].split("?")[0] or f"attachment_{len(requests)}"

            self._log.debug(f"Downloaded {attachment_type} attachment: {filename} (size: {len(file_data)} bytes, type: {mime_type})")

            # Classify based on attachment type and MIME type
            if attachment_type == "image" or (mime_type and mime_type.startswith("image/")):
                self._log.debug(f"Adding image: {filename}")
                requests.append(
                    AgentRequestImage(
                        image_data=file_data_base64,
                        name=filename,
                        mime_type=mime_type,
                    )
                )
            else:
                self._log.debug(f"Adding file: {filename}")
                requests.append(
                    AgentRequestFile(
                        file_data=file_data_base64,
                        name=filename,
                        mime_type=mime_type,
                    )
                )

        except Exception as e:
            self._log.error(f"Error processing attachment: {e}\n{traceback.format_exc()}")
            # Provide a user-facing indication that an attachment failed to process.
            try:
                requests.append(
                    AgentRequestText(text="I couldn't process one of your attachments. " "Please try again or send it in a different format.")
                )
            except Exception as inner_e:
                self._log.error(f"Error while adding attachment failure notice: {inner_e}\n{traceback.format_exc()}")

    async def _send_message(self, recipient_id: str, text: str):
        """
        Send a Messenger message using the Send API.

        :param recipient_id: Recipient user ID
        :param text: Message text
        """
        url = f"{self._base_url}/me/messages"

        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

        # Split message if it exceeds Messenger's limit (2000 characters)
        max_length = 2000
        messages = [text[i : i + max_length] for i in range(0, len(text), max_length)]

        async with httpx.AsyncClient() as client:
            for i, message_text in enumerate(messages):
                payload = {
                    "recipient": {"id": recipient_id},
                    "message": {"text": message_text},
                    "messaging_type": "RESPONSE",
                }

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

    async def _send_typing_indicator(self, recipient_id: str, typing_on: bool = True):
        """
        Send typing indicator to show the bot is processing.

        :param recipient_id: Recipient user ID
        :param typing_on: True to turn on typing indicator, False to turn off
        """
        url = f"{self._base_url}/me/messages"

        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

        payload = {
            "recipient": {"id": recipient_id},
            "sender_action": "typing_on" if typing_on else "typing_off",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                self._log.debug(f"Typing indicator {'on' if typing_on else 'off'}: {recipient_id}")
        except Exception as e:
            self._log.warning(f"Failed to send typing indicator: {e}")

    async def _mark_seen(self, recipient_id: str):
        """
        Mark message as seen.

        :param recipient_id: Recipient user ID
        """
        url = f"{self._base_url}/me/messages"

        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

        payload = {"recipient": {"id": recipient_id}, "sender_action": "mark_seen"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                self._log.debug(f"Message marked as seen: {recipient_id}")
        except Exception as e:
            self._log.warning(f"Failed to mark message as seen: {e}")
