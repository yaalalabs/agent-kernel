import logging
import traceback

import httpx
from fastapi import APIRouter, HTTPException, Request

from ...api import RESTRequestHandler
from ...core import AgentService, Config


class AgentTelegramRequestHandler(RESTRequestHandler):
    """
    API router that exposes endpoints to interact with Telegram Bot API using Agent Kernel.

    This handler uses Telegram Bot webhooks to receive messages and send responses.

    Endpoints:
    - GET /health: Health check
    - POST /telegram/webhook: Handle incoming Telegram updates
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.telegram")
        self._telegram_agent = Config.get().telegram.agent if Config.get().telegram.agent != "" else None
        self._bot_token = Config.get().telegram.bot_token
        self._webhook_secret = Config.get().telegram.webhook_secret
        self._api_version = Config.get().telegram.api_version or "bot"
        self._base_url = f"https://api.telegram.org/{self._api_version}{self._bot_token}"

        if not self._bot_token:
            self._log.error("Telegram bot token is not configured. Please set bot_token.")
            raise ValueError("Incomplete Telegram configuration.")

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.post("/telegram/webhook")
        async def handle_webhook(request: Request):
            """
            Handle incoming Telegram webhook updates.
            """
            return await self._handle_webhook(request)

        return router

    async def _handle_webhook(self, request: Request):
        """
        Handle incoming Telegram updates.

        :param request: FastAPI Request object
        :return: Success response
        """
        # Verify request signature if webhook secret is configured
        if self._webhook_secret:
            secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if secret_token != self._webhook_secret:
                self._log.warning("Invalid webhook secret token")
                raise HTTPException(status_code=403, detail="Invalid secret token")

        # Process the webhook payload
        try:
            body = await request.json()
            self._log.debug(f"Received Telegram update: {body}")

            # Handle different update types
            if "message" in body:
                await self._handle_message(body["message"])
            elif "edited_message" in body:
                await self._handle_edited_message(body["edited_message"])
            elif "callback_query" in body:
                await self._handle_callback_query(body["callback_query"])
            else:
                # Log unhandled update types
                update_keys = list(body.keys())
                self._log.debug(f"Unhandled update type: {update_keys}")

        except Exception as e:
            self._log.error(f"Error processing webhook: {e}\n{traceback.format_exc()}")

        return {"ok": True}

    async def _handle_message(self, message: dict):
        """
        Handle an individual Telegram message.

        :param message: Message object from update
        """
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        text = message.get("text")

        # Handle different message types
        if not text:

            self._log.warning("Message has no text content")
            return

        if not chat_id or not message_id:
            self._log.warning("Message missing required fields (chat_id/message_id)")
            return

        self._log.debug(f"Processing message {message_id} from chat {chat_id}: {text}")

        # Check if it's a bot command
        if text.startswith("/"):
            await self._handle_command(chat_id, text)
        else:
            await self._process_agent_message(chat_id, text)

    async def _handle_edited_message(self, message: dict):
        """
        Handle edited message.

        :param message: Edited message object
        """
        self._log.debug(f"Received edited message: {message}")
        # Treat edited messages the same as new messages
        await self._handle_message(message)

    async def _handle_callback_query(self, callback_query: dict):
        """
        Handle callback query from inline keyboards.

        :param callback_query: Callback query object
        """
        query_id = callback_query.get("id")
        data = callback_query.get("data")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")

        self._log.debug(f"Processing callback query {query_id}: {data}")

        # Answer the callback query to remove loading state
        await self._answer_callback_query(query_id, "Processing...")

        if chat_id and data:
            # Treat callback data as message text
            await self._process_agent_message(chat_id, data)

    async def _handle_command(self, chat_id: int, command: str):
        """
        Handle bot commands.

        :param chat_id: Chat ID
        :param command: Command text (e.g., "/start")
        """
        self._log.debug(f"Processing command: {command}")

        if command == "/start":
            await self._send_message(chat_id, "👋 Hello! I'm an AI assistant powered by Agent Kernel. How can I help you today?")
        elif command == "/help":
            await self._send_message(
                chat_id,
                "Send me any message and I'll respond using AI. Available commands:\n/start - Start conversation\n/help - Show this help",
            )
        else:
            # Unknown command - process as regular message
            await self._process_agent_message(chat_id, command)

    async def _process_agent_message(self, chat_id: int, message_text: str):
        """
        Process message through agent.

        :param chat_id: Chat ID
        :param message_text: Message text
        """
        service = AgentService()
        session_id = str(chat_id)  # Use chat_id as session_id

        try:
            # Send typing action
            await self._send_chat_action(chat_id, "typing")

            # Select and run agent
            service.select(session_id=session_id, name=self._telegram_agent)
            if not service.agent:
                self._log.warning(f"No agent available for name: {self._telegram_agent} (session_id: {session_id})")
                await self._send_message(chat_id, "Sorry, no agent is available to handle your request.")
                return

            # Run the agent
            result = await service.run(message_text)

            if hasattr(result, "raw"):
                response_text = str(result.raw)
            else:
                response_text = str(result)

            self._log.debug(f"Agent response: {response_text}")

            # Send the response
            await self._send_message(chat_id, response_text)

        except Exception as e:
            self._log.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            await self._send_message(chat_id, "Sorry, there was an error processing your request.")

    async def _send_message(self, chat_id: int, text: str, parse_mode: str = None, reply_markup: dict = None):
        """
        Send a message using Telegram Bot API.

        :param chat_id: Chat ID
        :param text: Message text
        :param parse_mode: Optional parse mode (Markdown, HTML, MarkdownV2)
        :param reply_markup: Optional inline keyboard markup
        """
        url = f"{self._base_url}/sendMessage"

        # Split message if it exceeds Telegram's limit (4096 characters)
        max_length = 4096
        messages = [text[i : i + max_length] for i in range(0, len(text), max_length)]

        async with httpx.AsyncClient() as client:
            for i, message_text in enumerate(messages):
                payload = {
                    "chat_id": chat_id,
                    "text": message_text,
                }

                if parse_mode:
                    payload["parse_mode"] = parse_mode

                # Only add reply_markup to the last message
                if reply_markup and i == len(messages) - 1:
                    payload["reply_markup"] = reply_markup

                try:
                    response = await client.post(url, json=payload)
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

    async def _send_chat_action(self, chat_id: int, action: str = "typing"):
        """
        Send chat action (typing indicator).

        :param chat_id: Chat ID
        :param action: Action type (typing, upload_photo, record_video, etc.)
        """
        url = f"{self._base_url}/sendChatAction"

        payload = {
            "chat_id": chat_id,
            "action": action,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                self._log.debug(f"Chat action '{action}' sent to {chat_id}")
        except Exception as e:
            self._log.warning(f"Failed to send chat action: {e}")

    async def _answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False):
        """
        Answer callback query.

        :param callback_query_id: Callback query ID
        :param text: Optional text to show
        :param show_alert: Whether to show as alert
        """
        url = f"{self._base_url}/answerCallbackQuery"

        payload = {
            "callback_query_id": callback_query_id,
        }

        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = show_alert

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                self._log.debug(f"Callback query answered: {callback_query_id}")
        except Exception as e:
            self._log.warning(f"Failed to answer callback query: {e}")
