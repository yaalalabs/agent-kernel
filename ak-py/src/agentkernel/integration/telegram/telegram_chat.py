import base64
import logging
import mimetypes
import traceback

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ...api import RESTRequestHandler
from ...core import AgentService, Config
from ...core.model import AgentRequestFile, AgentRequestImage, AgentRequestText


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
        self._http_timeout = 30.0  # Timeout for file downloads and API calls
        self._max_file_size = Config.get().api.max_file_size

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
        async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
            """
            Handle incoming Telegram webhook updates.
            """
            # Read body first to avoid stream consumption issues in background
            body = await request.json()
            background_tasks.add_task(self._process_webhook_body, body, request.headers)
            return {"ok": True}

        return router

    async def _process_webhook_body(self, body: dict, headers: Mapping[str, str]):
        """
        Process the webhook body in background.
        """
        # Verify request signature if webhook secret is configured
        if self._webhook_secret:
            secret_token = headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if secret_token != self._webhook_secret:
                self._log.warning("Invalid webhook secret token")
                return  # Can't raise HTTP exception here as response is sent

        try:
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

    async def _handle_message(self, message: dict):
        """
        Handle an individual Telegram message.

        :param message: Message object from update
        """
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        # Get text from either 'text' field (regular messages) or 'caption' field (media with captions)
        text = (message.get("text") or message.get("caption") or "").strip()

        if not chat_id or not message_id:
            self._log.warning("Message missing required fields (chat_id/message_id)")
            return

        # Check if message has text, files, or images
        has_text = bool(text)
        has_files = "document" in message
        has_images = "photo" in message

        if not has_text and not has_files and not has_images:
            self._log.warning("Message has no text, files, or images")
            return

        self._log.debug(f"Processing message {message_id} from chat {chat_id}")

        # Check if it's a bot command (only if it has text)
        if has_text and text.startswith("/"):
            await self._handle_command(chat_id, text)
        else:
            await self._process_agent_message(chat_id, text if has_text else "", message)

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

    async def _process_agent_message(self, chat_id: int, message_text: str, message: dict | None = None):
        """
        Process message through agent.

        :param chat_id: Chat ID
        :param message_text: Message text
        :param message: Full message dict from Telegram (for accessing files/images)
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

            # Build requests list with text and files/images
            requests = []

            # Add text if present
            if message_text:
                requests.append(AgentRequestText(text=message_text))

            # Process files and images if message object is provided
            if message:
                failed_files = await self._process_files(message, requests)
                if failed_files:
                    self._log.warning(f"Failed to process files: {failed_files}")

            # If no content at all, nothing to process
            if not requests:
                self._log.warning("No valid content found in message")
                await self._send_message(chat_id, "Sorry, your message appears to be empty.")
                return

            # Run the agent with all requests (text + files/images)
            result = await service.run_multi(requests=requests)

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

        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
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
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
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
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                self._log.debug(f"Callback query answered: {callback_query_id}")
        except Exception as e:
            self._log.warning(f"Failed to answer callback query: {e}")

    async def _get_file_info(self, file_id: str):
        """
        Get file information from Telegram API.

        :param file_id: File ID from Telegram
        :return: File info dict with file_path
        """
        url = f"{self._base_url}/getFile"
        payload = {"file_id": file_id}

        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                if result.get("ok"):
                    return result.get("result")
                else:
                    self._log.error(f"Failed to get file info: {result}")
                    return None
        except Exception as e:
            self._log.error(f"Error getting file info: {e}")
            return None

    async def _download_telegram_file(self, file_path: str) -> bytes | None:
        """
        Download file content from Telegram server.

        :param file_path: File path from getFile API
        :return: File content as bytes
        """
        url = f"https://api.telegram.org/file/bot{self._bot_token}/{file_path}"

        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except Exception as e:
            self._log.error(f"Error downloading file from Telegram: {e}")
            return None

    async def _process_files(self, message: dict, requests: list) -> list[str]:
        """
        Process files and images in a Telegram message.

        :param message: Message object from Telegram
        :param requests: List to append AgentRequestFile/AgentRequestImage objects
        :return: List of failed file names
        """
        failed_files = []

        # Process photos (images)
        if "photo" in message:
            photos = message.get("photo", [])
            if photos:
                # Get the largest photo
                largest_photo = photos[-1]
                file_id = largest_photo.get("file_id")

                try:
                    self._log.debug(f"Processing photo: {file_id}")

                    # Get file info
                    file_info = await self._get_file_info(file_id)
                    if file_info:
                        file_path = file_info.get("file_path")
                        file_size = file_info.get("file_size")

                        # Skip before download only if we have a known positive size that exceeds the limit
                        if isinstance(file_size, int) and file_size > 0 and file_size > self._max_file_size:
                            self._log.warning(f"Photo is too large to process ({file_size} bytes > {self._max_file_size} bytes). Skipping.")
                            failed_files.append("photo")
                        else:
                            # Download file (size unknown or within declared limit)
                            file_content = await self._download_telegram_file(file_path)
                            if file_content is not None:
                                content_size = len(file_content)
                                if content_size > self._max_file_size:
                                    self._log.warning(
                                        f"Downloaded photo is too large ({content_size} bytes > {self._max_file_size} bytes). Skipping."
                                    )
                                    failed_files.append("photo")
                                else:
                                    # Base64 encode
                                    image_data_base64 = base64.b64encode(file_content).decode("utf-8")

                                    # Detect actual MIME type from file path
                                    photo_name = file_path.rsplit("/", 1)[-1] if file_path else "photo"
                                    guessed_mime_type, _ = mimetypes.guess_type(file_path or "")
                                    photo_mime_type = guessed_mime_type or "image/jpeg"

                                    # Add as image request
                                    requests.append(
                                        AgentRequestImage(
                                            image_data=image_data_base64,
                                            name=photo_name,
                                            mime_type=photo_mime_type,
                                        )
                                    )
                                    self._log.debug(f"Added photo to request (size: {content_size} bytes)")
                            else:
                                self._log.warning(f"Failed to download photo")
                                failed_files.append("photo")
                    else:
                        self._log.warning("Failed to get photo file info")
                        failed_files.append("photo")

                except Exception as e:
                    self._log.error(f"Error processing photo: {e}\n{traceback.format_exc()}")
                    failed_files.append("photo")

        # Process documents (files)
        if "document" in message:
            document = message.get("document", {})
            file_id = document.get("file_id")
            file_name = document.get("file_name", "document")
            mime_type = document.get("mime_type", "application/octet-stream")

            try:
                self._log.debug(f"Processing document: {file_id} ({file_name})")

                # Get file info
                file_info = await self._get_file_info(file_id)
                if file_info:
                    file_path = file_info.get("file_path")
                    file_size = file_info.get("file_size")

                    # Skip before download only if we have a known positive size that exceeds the limit
                    if isinstance(file_size, int) and file_size > 0 and file_size > self._max_file_size:
                        self._log.warning(f"File '{file_name}' is too large to process ({file_size} bytes > {self._max_file_size} bytes). Skipping.")
                        failed_files.append(file_name)
                    else:
                        # Download file (size unknown or within declared limit)
                        file_content = await self._download_telegram_file(file_path)
                        if file_content is not None:
                            content_size = len(file_content)
                            if content_size > self._max_file_size:
                                self._log.warning(
                                    f"Downloaded file '{file_name}' is too large ({content_size} bytes > {self._max_file_size} bytes). Skipping."
                                )
                                failed_files.append(file_name)
                            else:
                                # Base64 encode
                                file_data_base64 = base64.b64encode(file_content).decode("utf-8")

                                # Add as file request
                                requests.append(
                                    AgentRequestFile(
                                        file_data=file_data_base64,
                                        name=file_name,
                                        mime_type=mime_type,
                                    )
                                )
                                self._log.debug(f"Added file to request: {file_name} (size: {content_size} bytes)")
                        else:
                            self._log.warning(f"Failed to download file: {file_name}")
                            failed_files.append(file_name)
                else:
                    self._log.warning(f"Failed to get file info for {file_name}")
                    failed_files.append(file_name)

            except Exception as e:
                self._log.error(f"Error processing document: {e}\n{traceback.format_exc()}")
                failed_files.append(file_name)

        return failed_files
