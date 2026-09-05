"""Slack inbound/outbound adapter pair (spec #524 §9).

Slack is one of the two platforms whose SDK owns the HTTP response: Bolt's request handler
verifies the signature, answers the ``url_verification`` handshake, and dispatches to the
registered listener. So ``verify`` stays the base no-op and ``parse`` runs Bolt's dispatch,
handing Bolt's own response back for the host to return.
"""

import base64
import contextvars
import logging
import os
import traceback
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequest, AgentRequestAny, AgentRequestFile, AgentRequestImage, AgentRequestText
from ...core.multimodal.storage.offload import offload_attachments
from ..adapter.base import (
    ATTACHMENTS_DISABLED_ERROR,
    SESSION_CACHE_ERROR,
    InboundAdapter,
    InboundParseResult,
    InboundRequest,
    OutboundAdapter,
)

NAME = "slack"
_events: contextvars.ContextVar[List[dict]] = contextvars.ContextVar("ak_slack_events")


class SlackInboundAdapter(InboundAdapter):
    """Slack events -> normalized requests."""

    name = NAME
    webhook_path = "/slack/events"

    _log = logging.getLogger("ak.integration.slack")

    def __init__(self):
        config = AKConfig.get()
        self._agent = config.slack.agent or None
        self._max_file_size = config.api.max_file_size
        self._bot_id: Optional[str] = None

        self._app = AsyncApp(
            process_before_response=True,
        )
        self._handler = AsyncSlackRequestHandler(self._app)

        @self._app.event("message")
        async def _collect(message):
            collected = _events.get(None)
            if collected is not None:
                collected.append(message)

    async def parse(self, raw: Request) -> InboundParseResult:
        """Run Bolt's dispatch and normalize whatever message events it produced."""
        token = _events.set([])
        try:
            response = await self._handler.handle(raw)
            events = _events.get()
        finally:
            _events.reset(token)

        requests = []
        for event in events:
            inbound = await self._to_request(event)
            if inbound is not None:
                requests.append(inbound)
        return InboundParseResult(requests=requests, response=response)

    async def _to_request(self, body: dict) -> Optional[InboundRequest]:
        """Normalize one Slack message event, or None when it is not for us."""
        user = body.get("user")
        channel = body.get("channel")
        if not user or not channel:
            return None
        text = body.get("text", "")
        files = body.get("files", [])
        thread_ts = body.get("thread_ts") or body.get("ts")

        if user == await self._bot_user_id():
            return None

        question = text.replace(f"<@{self._bot_id}>", "").strip()
        self._log.debug(f"Received request from user {user} in channel {channel}: {question}")

        rejected = [f.get("name", "file") for f in files if (f.get("mimetype") or "").startswith(("audio/", "video/"))]
        if rejected:
            await self._say(
                channel,
                thread_ts,
                "I can only process text messages, images, and document files. "
                f"The following audio/video files were rejected: {', '.join(rejected)}",
            )
            return None

        oversized = [
            f"{f.get('name', 'file')} ({f.get('size', 0) / (1024 * 1024):.2f} MB)"
            for f in files
            if not (f.get("mimetype") or "").startswith(("audio/", "video/")) and f.get("size", 0) > self._max_file_size
        ]
        if oversized:
            await self._say(
                channel,
                thread_ts,
                f"Sorry <@{user}>, the following files exceed the maximum size of "
                f"{self._max_file_size / (1024 * 1024):.2f} MB: {', '.join(oversized)}",
            )
            return None

        requests: List[AgentRequest] = []
        if question:
            requests.append(AgentRequestText(prompt=question))

        failed = await self._process_files(files, requests) if files else []
        if failed:
            await self._say(channel, thread_ts, f"Sorry <@{user}>, I could not download the following files: {', '.join(failed)}. Please try again.")
            return None

        if not requests:
            await self._say(channel, thread_ts, "Please provide a message or attachment.")
            return None

        requests, _ = offload_attachments(
            thread_ts,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )
        requests.append(AgentRequestAny(name="body", content=body))

        return InboundRequest(
            session_id=thread_ts,
            request_id=f"slack:{channel}:{body.get('ts')}",
            requests=requests,
            prompt=question,
            agent=self._agent,
            user_id=user,
            group_id=channel,
            reply_context={"channel": channel, "thread_ts": thread_ts, "user": user},
        )

    async def _bot_user_id(self) -> Optional[str]:
        """The bot's own user id, so its own messages are ignored. Resolved once."""
        if self._bot_id is None:
            self._bot_id = (await self._app.client.auth_test())["user_id"]
        return self._bot_id

    async def _say(self, channel: str, thread_ts: Optional[str], text: str) -> None:
        """Post a rejection notice from the edge, where the user is still waiting."""
        try:
            await self._app.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
        except Exception as e:
            self._log.error(f"Could not post a Slack message: {e}")

    async def _process_files(self, files: list, requests: List[AgentRequest]) -> List[str]:
        """Download each file and append it to ``requests``.

        :return: Names of the files that could not be downloaded.
        """
        failed: List[str] = []
        for file in files:
            file_name = file.get("name", "unknown")
            try:
                mime_type = file.get("mimetype")
                url_private = file.get("url_private")
                if not url_private:
                    self._log.warning(f"No URL found for file: {file_name}")
                    failed.append(file_name)
                    continue

                content = await self._download(url_private)
                if content is None:
                    failed.append(f"{file_name} ({url_private})")
                    continue

                encoded = base64.b64encode(content).decode("utf-8")
                if mime_type and mime_type.startswith("image/"):
                    requests.append(AgentRequestImage(image_data=encoded, name=file_name, mime_type=mime_type))
                else:
                    requests.append(AgentRequestFile(file_data=encoded, name=file_name, mime_type=mime_type))
            except Exception as e:
                self._log.error(f"Error processing file {file_name}: {e}\n{traceback.format_exc()}")
                failed.append(file_name)
        return failed

    async def _download(self, url: str) -> Optional[bytes]:
        """Download a private Slack file with the bot token."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers={"Authorization": f"Bearer {self._app.client.token}"}, timeout=30.0)
                response.raise_for_status()
                return response.content
        except Exception as e:
            self._log.error(f"Error downloading file from {url}: {e}")
            return None


class SlackOutboundAdapter(OutboundAdapter):
    """Agent replies -> Slack messages."""

    name = NAME
    MESSAGE_LIMIT = 3000
    MAX_CHUNKS = 5
    TRUNCATION_NOTICE = "Response is truncated due to size restrictions in Slack"

    _log = logging.getLogger("ak.integration.slack")

    def __init__(self):
        self._acknowledgement = AKConfig.get().slack.agent_acknowledgement or None

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        """Post the "thinking" message, if one is configured, and remember where it went."""
        if not self._acknowledgement:
            return {}
        try:
            posted = await self._client().chat_postMessage(
                channel=reply_context["channel"],
                thread_ts=reply_context.get("thread_ts"),
                text=f"Hi <@{reply_context.get('user')}>, {self._acknowledgement} :rolling-loader:",
            )
            return {"ack_ts": posted["ts"], "ack_channel": posted["channel"]}
        except Exception as e:
            self._log.warning(f"Could not post the Slack acknowledgement: {e}")
            return {}

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        """Clear the loading indicator, then post the reply in the originating thread."""
        client = self._client()
        channel = reply_context.get("ack_channel") or reply_context["channel"]
        thread_ts = reply_context.get("ack_ts") or reply_context.get("thread_ts")

        if reply_context.get("ack_ts"):
            await client.chat_update(channel=channel, ts=reply_context["ack_ts"], text=f"Hi <@{reply_context.get('user')}>,")

        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Agent response",
            blocks=self.split_reply(str(reply)),
            metadata={"event_type": "first_pass", "event_payload": {"id": thread_ts}},
        )

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        try:
            await self._client().chat_postMessage(channel=reply_context["channel"], text=message)
        except Exception as e:
            self._log.error(f"Could not deliver the Slack error message: {e}")

    def split_reply(self, text: str) -> list:
        """Chunk the reply into Slack section blocks."""
        chunks = [text[i : i + self.MESSAGE_LIMIT] for i in range(0, len(text), self.MESSAGE_LIMIT)] or [""]
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": chunk}} for chunk in chunks[: self.MAX_CHUNKS]]
        if len(chunks) > self.MAX_CHUNKS:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": self.TRUNCATION_NOTICE}})
        return blocks

    @staticmethod
    def _client() -> AsyncWebClient:
        """A fresh client per call: each delivery runs on its own event loop."""
        return AsyncWebClient(token=os.environ.get("SLACK_BOT_TOKEN"))
