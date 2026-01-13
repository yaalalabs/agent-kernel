import base64
import logging
import traceback

import httpx
from fastapi import APIRouter, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from ...api import RESTRequestHandler
from ...core import AgentService, Config
from ...core.model import AgentReplyImage, AgentReplyText, AgentRequestFile, AgentRequestImage, AgentRequestText


class AgentSlackRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Slack using Agent Kernel.
    Endpoints:
    - GET /health: Health check
    - GET /agents: List available agents. Not used by Slack but useful for testing.
    - POST /slack/events: Handle Slack events
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.slack")
        self._slack_agent = Config.get().slack.agent if Config.get().slack.agent != "" else None
        self._slack_agent_acknowledgement = Config.get().slack.agent_acknowledgement if Config.get().slack.agent_acknowledgement != "" else None
        self._max_file_size = Config.get().api.max_file_size
        self._bot_id = None

        # Initialize the Slack app
        self._slack_app = AsyncApp()
        self._handler = AsyncSlackRequestHandler(self._slack_app)
        slack_app = self._slack_app

        @slack_app.event("message")  # trigger this for any message event
        async def handle_messages(message, say):
            await self.handle(message, say)

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.post("/slack/events")
        async def slack_events(req: Request):
            body = await req.json()
            self._log.debug(f"Received Slack event: {body}")
            return await self._handler.handle(req)

        return router

    async def handle(self, body: dict, say):
        """
        Async method to run the agent.
        :param body: dict containing Slack message data.
        :param say: function for sending messages back to Slack.
        """
        user = body["user"]
        text = body.get("text", "")
        channel = body["channel"]
        files = body.get("files", [])

        # in Slack, thread_ts is populated if its a thread message if not, use ts
        thread_ts = body.get("thread_ts", None) or body["ts"]
        if self._bot_id is None:
            self._bot_id = (await self._slack_app.client.auth_test())["user_id"]

        # Avoid the bot responding to its own messages
        if user == self._bot_id:
            return

        mention = f"<@{self._bot_id}>"
        question = text.replace(mention, "").strip()

        self._log.debug(f"Received request from user {user} in channel {channel}: {question}")

        service = AgentService()
        try:
            # Check for audio/video files and reject them
            rejected_files = []
            oversized_files = []
            for file in files:
                mime_type = file.get("mimetype", "")
                file_name = file.get("name", "file")
                file_size = file.get("size", 0)

                if mime_type.startswith(("audio/", "video/")):
                    rejected_files.append(file_name)
                elif file_size > self._max_file_size:
                    oversized_files.append(f"{file_name} ({file_size / (1024 * 1024):.2f} MB)")

            if rejected_files:
                await say(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=(
                        "I can only process text messages, images, and document files. "
                        f"The following audio/video files were rejected: {', '.join(rejected_files)}"
                    ),
                )
                return

            if oversized_files:
                await say(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"Sorry <@{user}>, the following files exceed the maximum size of {self._max_file_size / (1024 * 1024):.2f} MB: {', '.join(oversized_files)}",
                )
                return

            response_for_first_bot_message = None
            if self._slack_agent_acknowledgement is not None:
                response_for_first_bot_message = await say(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"Hi <@{user}>, {self._slack_agent_acknowledgement} :rolling-loader:",
                )
            service.select(session_id=thread_ts, name=self._slack_agent)
            if not service.agent:
                await say(channel=channel, text="No agent available to handle your request.")
                return

            # Build requests list with text, files, and images
            requests = []
            if question:
                requests.append(AgentRequestText(text=question))

            # Process files and images
            failed_files = []
            if files:
                failed_files = await self._process_files(files, requests)

            # If any files failed to download, notify user and do not invoke agent
            if failed_files:
                await say(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"Sorry <@{user}>, I could not download the following files: {', '.join(failed_files)}. Please try again.",
                )
                return

            # Use run_multi
            if len(requests) > 0:
                result = await service.run_multi(requests=requests)
            else:
                await say(channel=channel, thread_ts=thread_ts, text="Please provide a message or attachment.")
                return

            response_text = str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received"

            # This will update the initial message to remove the loading text emoji
            if response_for_first_bot_message is not None:
                new_ts = response_for_first_bot_message["ts"]
                ch = response_for_first_bot_message["channel"]
                await say.client.chat_update(channel=ch, ts=new_ts, text=f"Hi <@{user}>,")
            else:
                new_ts = thread_ts
                ch = channel

            self._log.debug(f"Agent response: {response_text}")

            # post final reply
            await say(
                text="Agent response",
                blocks=self._split_reply(response_text),
                channel=ch,
                thread_ts=new_ts,
                metadata={"event_type": "first_pass", "event_payload": {"id": new_ts}},
            )

        except SlackApiError as e:
            self._log.error(f"Slack API Error: {e.response['error']}")
        except Exception as e:
            self._log.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            await say(channel=channel, text="Error handling your request.")
            return

    def _split_reply(self, reply: str) -> list:
        """
        Prepares the reply text.
        :param reply: The reply text.
        :return: The prepared reply text.
        """
        response_chunks = [reply[i : i + 3000] for i in range(0, len(reply), 3000)]  # Current max chunk size in slack is 3000 characters

        blocks = []
        for i in range(len(response_chunks)):
            if i < 5:  # Limit to first 5 chunks:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": response_chunks[i]},
                    }
                )
            else:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Response is truncated due to size restrictions in Slack",
                        },
                    }
                )
                break

        return blocks

    async def _process_files(self, files: list, requests: list) -> list[str]:
        """
        Process files from Slack message and add them to requests list.
        Files are validated for size limits before download.
        :param files: List of file objects from Slack message.
        :param requests: List to append AgentRequestFile or AgentRequestImage objects.
        :return: List of file names/URLs that failed to download.
        """
        failed_files = []

        for file in files:
            try:
                file_name = file.get("name", "unknown")
                mime_type = file.get("mimetype", None)
                url_private = file.get("url_private")

                if not url_private:
                    self._log.warning(f"No URL found for file: {file_name}")
                    failed_files.append(file_name)
                    continue

                self._log.debug(f"Downloading file: {file_name} (type: {mime_type}) from {url_private}")

                # Download file content from Slack
                file_content = await self._download_slack_file(url_private)

                if file_content is None:
                    self._log.warning(f"Failed to download file: {file_name} from {url_private}")
                    failed_files.append(f"{file_name} ({url_private})")
                    continue

                # Base64 encode the content
                file_data_base64 = base64.b64encode(file_content).decode("utf-8")

                # Classify as image or regular file based on MIME type
                if mime_type and mime_type.startswith("image/"):
                    self._log.debug(f"Adding image: {file_name}")
                    requests.append(
                        AgentRequestImage(
                            image_data=file_data_base64,
                            name=file_name,
                            mime_type=mime_type,
                        )
                    )
                else:
                    self._log.debug(f"Adding file: {file_name}")
                    requests.append(
                        AgentRequestFile(
                            file_data=file_data_base64,
                            name=file_name,
                            mime_type=mime_type,
                        )
                    )

            except Exception as e:
                file_name = file.get("name", "unknown")
                self._log.error(f"Error processing file {file_name}: {e}\n{traceback.format_exc()}")
                failed_files.append(file_name)

        return failed_files

    async def _download_slack_file(self, url: str) -> bytes | None:
        """
        Download a file from Slack using the bot token for authentication.
        :param url: The private URL of the file to download.
        :return: File content as bytes, or None if download fails.
        """
        try:
            # Get the bot token from the Slack app
            token = self._slack_app.client.token

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.content

        except httpx.HTTPError as e:
            self._log.error(f"HTTP error downloading file from {url}: {e}")
            return None
        except Exception as e:
            self._log.error(f"Error downloading file from {url}: {e}\n{traceback.format_exc()}")
            return None
