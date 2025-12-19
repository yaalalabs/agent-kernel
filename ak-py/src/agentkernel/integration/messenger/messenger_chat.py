import base64
import hashlib
import hmac
import logging
import traceback

import httpx
from fastapi import APIRouter, HTTPException, Request

from ...api import RESTRequestHandler
from ...core import (
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentService,
    Config,
)


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
        message_text = message.get("text")
        attachments = message.get("attachments", [])

        if not sender_id or not message_id:
            self._log.warning("Message missing required fields (sender/mid)")
            return

        # Allow message if it has text OR attachments
        if not message_text and not attachments:
            self._log.warning("Message has no text or attachments")
            return

        if message_text:
            self._log.debug(f"Processing message {message_id} from {sender_id}: {message_text}")
        if attachments:
            self._log.debug(f"Processing message {message_id} from {sender_id} with {len(attachments)} attachment(s)")
        await self._process_agent_message(sender_id, message_text or "", attachments)

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
        if attachments is None:
            attachments = []

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

            # Extract and download attachments
            processed_attachments = await self._extract_attachments(attachments)

            # Get session to store/retrieve attachment history
            session = service.session

            # Store current attachment metadata in session
            if processed_attachments:
                self._store_attachment_metadata(session, processed_attachments)

            # Build request list: start with text only if it's not empty
            requests = []
            if message_text.strip():  # Only add text if it's not empty
                requests.append(AgentRequestText(text=message_text))
            requests.extend(processed_attachments)

            # Add conversation context if available
            conversation_context = self._get_conversation_context(session)
            if conversation_context:
                requests.insert(0, AgentRequestText(text=conversation_context))
                self._log.info(f"[AGENT_CONTEXT] Added conversation history to context")

            # Add previous attachments to the request if available
            previous_attachments = self._get_previous_attachments(session, processed_attachments)
            self._log.info(f"[DEBUG] previous_attachments returned: {len(previous_attachments)} items")
            if previous_attachments:
                for att in previous_attachments:
                    self._log.info(
                        f"[DEBUG] Previous attachment: name={getattr(att, 'name', '?')}, has_data={bool(getattr(att, 'image_data' if 'Image' in type(att).__name__ else 'file_data', None))}"
                    )
                requests.extend(previous_attachments)
                self._log.info(f"[AGENT_CONTEXT] Added {len(previous_attachments)} previous attachment(s) to context")
            else:
                self._log.info(f"[DEBUG] No previous attachments to add")

            # Log request summary
            self._log.info(
                f"[AGENT_INPUT] Total requests: {len(requests)} (text + {len(processed_attachments)} attachment(s) + context)"
            )

            # Store user message in conversation history for context (before agent runs)
            if message_text.strip():
                self._store_user_message(session, message_text)
            elif processed_attachments:
                # Even if no text, store that user sent attachment(s) for context
                attachment_names = [getattr(att, "name", "file") for att in processed_attachments]
                self._store_user_message(session, f"[sent image/file: {', '.join(attachment_names)}]")

            # Run the agent - always use run_multi if there are requests
            if len(requests) > 0:
                self._log.info(
                    f"[AGENT_CALL] Running agent with {len(requests)} request(s) (text + {len(processed_attachments)} attachment(s))"
                )
                result = await service.run_multi(requests)
            else:
                # No requests at all - nothing to process
                self._log.warning("No text or attachments to process")
                await self._send_message(sender_id, "Please send a message or attachment.")
                await self._send_typing_indicator(sender_id, False)
                return

            if hasattr(result, "raw"):
                response_text = str(result.raw)
            else:
                response_text = str(result)

            self._log.debug(f"Agent response: {response_text}")

            # Store agent response in session for context
            self._store_agent_response(session, response_text)

            # Turn off typing indicator and send the response
            await self._send_typing_indicator(sender_id, False)
            await self._send_message(sender_id, response_text)

        except Exception as e:
            self._log.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            await self._send_typing_indicator(sender_id, False)
            await self._send_message(sender_id, "Sorry, there was an error processing your request.")

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

    async def _extract_attachments(self, attachments: list) -> list:
        """
        Extract and download attachments from Messenger message.
        Messenger format: [{"type": "image", "payload": {"url": "..."}}]

        :param attachments: List of attachment objects from Messenger webhook
        :return: List of AgentRequestImage or AgentRequestFile objects
        """
        processed_attachments = []

        if not attachments:
            return processed_attachments

        try:
            async with httpx.AsyncClient() as client:
                for attachment in attachments:
                    attachment_type = attachment.get("type", "")
                    payload = attachment.get("payload", {})
                    url = payload.get("url")

                    if not url:
                        self._log.warning("Attachment missing URL")
                        continue

                    try:
                        # Download attachment
                        response = await client.get(url)
                        response.raise_for_status()

                        # Get MIME type from Content-Type header
                        mime_type = response.headers.get("content-type", "application/octet-stream").split(";")[0]

                        # Convert to base64
                        file_data = base64.b64encode(response.content).decode("utf-8")

                        # Extract filename from URL or use default
                        filename = url.split("/")[-1].split("?")[0] or f"attachment_{len(processed_attachments)}"

                        # Create appropriate request object
                        if attachment_type == "image" or mime_type.startswith("image/"):
                            request = AgentRequestImage(image_data=file_data, name=filename, mime_type=mime_type)
                            processed_attachments.append(request)
                            self._log.debug(f"Extracted image: {filename} ({mime_type})")

                        elif attachment_type == "file" or mime_type in [
                            "application/pdf",
                            "application/msword",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            "application/vnd.ms-excel",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        ]:
                            request = AgentRequestFile(file_data=file_data, name=filename, mime_type=mime_type)
                            processed_attachments.append(request)
                            self._log.debug(f"Extracted file: {filename} ({mime_type})")

                        else:
                            self._log.debug(f"Skipping unsupported attachment type: {mime_type}")

                    except Exception as e:
                        self._log.warning(f"Error downloading attachment from {url}: {e}")
                        continue

        except Exception as e:
            self._log.warning(f"Error processing attachments: {e}\n{traceback.format_exc()}")

        if processed_attachments:
            self._log.info(f"Extracted {len(processed_attachments)} attachment(s)")

        return processed_attachments

    def _store_attachment_metadata(self, session, processed_attachments: list):
        """
        Store attachment data and metadata in session for future reference.
        Stores the actual base64-encoded data so images/files can be re-used.

        :param session: Agent session object
        :param processed_attachments: List of AgentRequestImage or AgentRequestFile objects
        """
        try:
            import json
            from datetime import datetime

            # Get existing attachment history
            history = session.get_data(key="attachment_history")
            if not history:
                history = []
            else:
                # Parse if it's a JSON string
                if isinstance(history, str):
                    history = json.loads(history)

            # Add new attachments with full data
            for attachment in processed_attachments:
                # Extract base64 data based on type
                if hasattr(attachment, "image_data"):
                    file_data = attachment.image_data
                elif hasattr(attachment, "file_data"):
                    file_data = attachment.file_data
                else:
                    file_data = None

                attachment_info = {
                    "name": getattr(attachment, "name", "unknown"),
                    "mime_type": getattr(attachment, "mime_type", "unknown"),
                    "type": type(attachment).__name__,  # AgentRequestImage or AgentRequestFile
                    "data": file_data,  # Store the actual base64 data
                    "timestamp": datetime.now().isoformat(),
                }
                history.append(attachment_info)
                self._log.debug(
                    f"Stored attachment in session: {attachment_info['name']} ({attachment_info['mime_type']})"
                )

            # Keep only last 10 attachments to avoid session bloat (full data takes more space)
            if len(history) > 10:
                history = history[-10:]

            # Store back to session
            session.set_data(key="attachment_history", data=json.dumps(history))
            self._log.info(
                f"[DEBUG] Stored {len(processed_attachments)} attachment(s) in session. Total history: {len(history)}"
            )
            self._log.info(f"[DEBUG] Attachment history keys: {[h['name'] for h in history]}")

        except Exception as e:
            self._log.warning(f"Error storing attachment data: {e}")

    def _get_previous_attachments(self, session, current_attachments: list) -> list:
        """
        Retrieve previous attachments from session and recreate request objects.
        Only returns attachments NOT in the current message (to avoid duplicates).

        :param session: Agent session object
        :param current_attachments: List of current attachments (to skip duplicates)
        :return: List of AgentRequestImage or AgentRequestFile objects from history
        """
        try:
            import json

            history = session.get_data(key="attachment_history")
            self._log.info(
                f"[DEBUG] Retrieved history from session: {type(history)}, length: {len(history) if history else 0}"
            )

            if not history:
                self._log.info(f"[DEBUG] History is empty or None")
                return []

            # Parse if it's a JSON string
            if isinstance(history, str):
                history = json.loads(history)
                self._log.info(f"[DEBUG] Parsed JSON history, items: {len(history)}")

            if not history:
                return []

            # Get names of current attachments to skip duplicates
            current_names = {getattr(att, "name", "") for att in current_attachments}
            self._log.info(f"[DEBUG] Current attachment names: {current_names}")

            # Recreate request objects from history (excluding current)
            previous_attachments = []
            for attachment_info in history:
                att_name = attachment_info.get("name", "unknown")
                self._log.info(
                    f"[DEBUG] Checking history item: {att_name}, in current_names? {att_name in current_names}"
                )

                # Skip if it's in the current message
                if att_name in current_names:
                    self._log.info(f"[DEBUG] Skipping {att_name} (duplicate)")
                    continue

                attachment_type = attachment_info.get("type", "AgentRequestFile")
                mime_type = attachment_info.get("mime_type", "unknown")
                file_data = attachment_info.get("data")
                name = attachment_info.get("name", "unknown")

                if not file_data:
                    self._log.warning(f"[DEBUG] No file_data for {name}")
                    continue

                # Recreate the appropriate request object
                try:
                    if attachment_type == "AgentRequestImage":
                        request = AgentRequestImage(image_data=file_data, name=name, mime_type=mime_type)
                        previous_attachments.append(request)
                        self._log.info(f"[DEBUG] Recreated image: {name} ({len(file_data)} bytes)")
                    elif attachment_type == "AgentRequestFile":
                        request = AgentRequestFile(file_data=file_data, name=name, mime_type=mime_type)
                        previous_attachments.append(request)
                        self._log.info(f"[DEBUG] Recreated file: {name} ({len(file_data)} bytes)")
                    else:
                        self._log.warning(f"[DEBUG] Unknown attachment type: {attachment_type}")
                except Exception as e:
                    self._log.warning(f"Error recreating attachment {name}: {e}")
                    continue

            self._log.info(f"[DEBUG] Total previous attachments recreated: {len(previous_attachments)}")
            return previous_attachments

        except Exception as e:
            self._log.warning(f"Error retrieving previous attachments: {e}\n{traceback.format_exc()}")
            return []

    def _store_agent_response(self, session, response_text: str):
        """
        Store agent response in session for conversation context.
        Helps agent understand what it already said in previous turns.

        :param session: Agent session object
        :param response_text: Agent's response text
        """
        try:
            import json
            from datetime import datetime

            # Get existing conversation history
            history = session.get_data(key="conversation_history")
            if not history:
                history = []
            else:
                # Parse if it's a JSON string
                if isinstance(history, str):
                    history = json.loads(history)

            # Add agent response
            history.append(
                {
                    "role": "agent",
                    "content": response_text,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Keep only last 20 exchanges to avoid session bloat
            if len(history) > 20:
                history = history[-20:]

            # Store back to session
            session.set_data(key="conversation_history", data=json.dumps(history))
            self._log.info(f"[DEBUG] Stored agent response in conversation history. Total: {len(history)}")

        except Exception as e:
            self._log.warning(f"Error storing agent response: {e}")

    def _store_user_message(self, session, message_text: str):
        """
        Store user message in session for conversation context.
        Helps agent understand the full conversation flow and context.

        :param session: Agent session object
        :param message_text: User's message text
        """
        try:
            import json
            from datetime import datetime

            # Get existing conversation history
            history = session.get_data(key="conversation_history")
            if not history:
                history = []
            else:
                # Parse if it's a JSON string
                if isinstance(history, str):
                    history = json.loads(history)

            # Add user message
            history.append(
                {
                    "role": "user",
                    "content": message_text,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Keep only last 20 exchanges to avoid session bloat
            if len(history) > 20:
                history = history[-20:]

            # Store back to session
            session.set_data(key="conversation_history", data=json.dumps(history))
            self._log.info(f"[DEBUG] Stored user message in conversation history. Total: {len(history)}")

        except Exception as e:
            self._log.warning(f"Error storing user message: {e}")

    def _get_conversation_context(self, session) -> str:
        """
        Retrieve conversation history and format as context for agent.
        Helps agent understand what was already discussed.

        :param session: Agent session object
        :return: Formatted conversation context string
        """
        try:
            import json

            history = session.get_data(key="conversation_history")
            if not history:
                return ""

            # Parse if it's a JSON string
            if isinstance(history, str):
                history = json.loads(history)

            if not history:
                return ""

            # Format as readable context
            context_lines = ["[Previous conversation context:"]
            for item in history[-10:]:  # Last 10 messages to cover multi-turn conversations
                role = item.get("role", "unknown")
                content = item.get("content", "")
                # Truncate long responses to 200 chars
                if len(content) > 200:
                    content = content[:200] + "..."
                context_lines.append(f"  {role}: {content}")
            context_lines.append("]")

            result = "\n".join(context_lines)
            self._log.info(f"[DEBUG] Retrieved conversation context ({len(history)} items)")
            return result

        except Exception as e:
            self._log.warning(f"Error retrieving conversation context: {e}")
            return ""
