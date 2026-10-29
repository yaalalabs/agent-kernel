"""Slack inbound/outbound adapter pair (spec #524 §9).

Slack is one of the two platforms whose SDK owns the HTTP response: Bolt's request handler
verifies the signature, answers the ``url_verification`` handshake, and dispatches to the
registered listener. So ``verify`` stays the base no-op and ``parse`` runs Bolt's dispatch,
handing Bolt's own response back for the host to return.
"""

import base64
import contextvars
import json
import logging
import os
import re
import traceback
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from ...core.config import AKConfig
from ...core.event import PausedInterruption
from ...core.model import (
    AgentPausedReplyAny,
    AgentReply,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
    ResumeDecision,
)
from ...core.multimodal.storage import AttachmentStorageManager
from ..adapter.base import (
    ATTACHMENTS_DISABLED_ERROR,
    SESSION_CACHE_ERROR,
    InboundAdapter,
    InboundParseResult,
    InboundRequest,
    OutboundAdapter,
)
from ..adapter.routes import BUILTIN_WEBHOOK_ROUTES

NAME = "slack"

ACTION_PREFIX = "ak_decision:"
"""Marks a Block Kit button as a decision on a paused run; the listener matches on it."""
REASON_PREFIX = "ak_decision_reason:"
"""Marks a button that opens the reason modal instead of deciding outright."""
MODAL_CALLBACK_ID = "ak_decision_reason_modal"
REASON_BLOCK_ID = "ak_reason"
REASON_INPUT_ID = "ak_reason_input"
BLOCK_PREFIX = "ak_pause:"
"""Prefixes the ``block_id`` of an actions block, which Slack asks to be unique per message."""
MAX_BLOCKS = 50
"""Slack's per-message block budget."""
BLOCK_ID_LIMIT = 255
VALUE_LIMIT = 2000
"""Slack's caps on a ``block_id`` and a button ``value``; over either, it rejects the whole message."""
DECISION_VERBS = ("approved", "denied", "cancelled")
BUTTON_LABELS = {"approved": "Approve", "denied": "Deny", "cancelled": "Cancel"}
BUTTON_STYLES = {"approved": "primary", "denied": "danger"}

_events: contextvars.ContextVar[List[dict]] = contextvars.ContextVar("ak_slack_events")
_presses: contextvars.ContextVar[List[dict]] = contextvars.ContextVar("ak_slack_presses")
_submissions: contextvars.ContextVar[List[dict]] = contextvars.ContextVar("ak_slack_submissions")


class SlackInboundAdapter(InboundAdapter):
    """Slack events -> normalized requests."""

    name = NAME
    webhook_path = BUILTIN_WEBHOOK_ROUTES[NAME].webhook_path

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

        @self._app.action(re.compile(f"^{re.escape(ACTION_PREFIX)}"))
        async def _collect_press(ack, body):
            """Collect a decision press. :meth:`parse` does the work, where no clock is running.

            ``process_before_response=True`` holds the HTTP response until this returns, so
            Slack's three seconds cover the whole listener, not merely the time before ``ack()``.
            """
            await ack()
            collected = _presses.get(None)
            if collected is not None:
                collected.append(body)

        @self._app.action(re.compile(f"^{re.escape(REASON_PREFIX)}"))
        async def _open_reason_modal(ack, body, client):
            """Ask why, instead of recording the denial from the press alone.

            The one Slack call made inside a listener, so ``views_open`` has to land in the same
            three seconds. A failure leaves the pause live: nothing was decided.
            """
            await ack()
            try:
                await client.views_open(trigger_id=body["trigger_id"], view=self._reason_modal(body))
            except Exception as e:
                self._log.error(f"Could not open the Slack reason modal: {e}")

        @self._app.view(MODAL_CALLBACK_ID)
        async def _collect_submission(ack, body):
            """Collect a submitted reason. Does no work, for the reason given above."""
            await ack()
            collected = _submissions.get(None)
            if collected is not None:
                collected.append(body)

    async def parse(self, raw: Request) -> InboundParseResult:
        """Run Bolt's dispatch and normalize whatever message events it produced.

        A delivery Slack is retrying after its own 3-second timeout is dropped: the first attempt
        already ran this listener to completion (Slack stopped waiting for the response, it did not
        stop the coroutine), so dispatching again would re-download the attachments and post a
        second acknowledgement for a message the transport's ``dedup_id`` will discard anyway.
        Only ``http_timeout`` retries short-circuit — an ``http_error`` retry is the platform
        recovering from a delivery this process genuinely failed, and it must run.
        """
        if raw.headers.get("x-slack-retry-reason") == "http_timeout":
            self._log.warning(
                f"Dropping Slack retry {raw.headers.get('x-slack-retry-num')} after a delivery timeout: the first "
                f"attempt completed out of band. Attachment downloads run inside Slack's 3s window "
                f"(process_before_response), so a large file can exceed it."
            )
            return InboundParseResult()

        events_token, presses_token, submissions_token = _events.set([]), _presses.set([]), _submissions.set([])
        try:
            response = await self._handler.handle(raw)
            events, presses, submissions = _events.get(), _presses.get(), _submissions.get()
        finally:
            _events.reset(events_token)
            _presses.reset(presses_token)
            _submissions.reset(submissions_token)

        requests = []
        for event in events:
            inbound = await self._to_request(event)
            if inbound is not None:
                requests.append(inbound)
        for press in presses:
            decision = self._decision_from_press(press)
            if decision is not None:
                requests.append(decision)
        for submission in submissions:
            decision = self._decision_from_modal(submission)
            if decision is not None:
                requests.append(decision)
        return InboundParseResult(requests=requests, response=response)

    def _decision_from_press(self, body: dict) -> Optional[InboundRequest]:
        """A Block Kit button press, as the decision it carries.

        The request id is composed from the press, not Slack's per-click ``action_ts``, so a
        second press deduplicates instead of reaching a pause already answered. The session is
        the thread the pause was posted into.

        :param body: The ``block_actions`` payload.
        :return: The decision as a request, or None when the payload does not carry one.
        """
        action = next(iter(body.get("actions") or []), {})
        parsed = self._parse_action_value(action.get("value"))
        channel = (body.get("channel") or {}).get("id")
        container, message = body.get("container") or {}, body.get("message") or {}
        message_ts = container.get("message_ts") or message.get("ts")
        thread_ts = container.get("thread_ts") or message.get("thread_ts") or message_ts
        if parsed is None or not channel or not thread_ts:
            return None

        interruption_id, status = parsed
        user = (body.get("user") or {}).get("id")
        reply_context = {"channel": channel, "thread_ts": thread_ts}
        if user:
            reply_context["user"] = user
        return InboundRequest(
            session_id=thread_ts,
            request_id=f"{NAME}:{channel}:{message_ts}:{interruption_id}:{status}",
            requests=[AgentResumeRequestAny(decisions=[ResumeDecision(id=interruption_id, status=status)])],
            agent=self._agent,
            user_id=user,
            group_id=channel,
            reply_context=reply_context,
        )

    def _reason_modal(self, body: dict) -> dict:
        """The modal a denial opens, carrying everything the submission will need back.

        A ``view_submission`` carries no channel and no message, so ``private_metadata`` carries
        the whole return address. The reason is optional: a denial must stay possible.

        :param body: The ``block_actions`` payload of the press that opened it.
        :return: The Slack view to open.
        """
        action = next(iter(body.get("actions") or []), {})
        container, message = body.get("container") or {}, body.get("message") or {}
        message_ts = container.get("message_ts") or message.get("ts")
        metadata = {
            "value": action.get("value"),
            "channel": (body.get("channel") or {}).get("id"),
            "ts": message_ts,
            "thread_ts": container.get("thread_ts") or message.get("thread_ts") or message_ts,
            "user": (body.get("user") or {}).get("id"),
        }
        return {
            "type": "modal",
            "callback_id": MODAL_CALLBACK_ID,
            "private_metadata": json.dumps(metadata),
            "title": {"type": "plain_text", "text": "Deny this request"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": REASON_BLOCK_ID,
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Reason"},
                    "element": {"type": "plain_text_input", "action_id": REASON_INPUT_ID, "multiline": True},
                }
            ],
        }

    def _decision_from_modal(self, body: dict) -> Optional[InboundRequest]:
        """A submitted reason, as the denial it completes.

        :param body: The ``view_submission`` payload.
        :return: The decision as a request, or None when the metadata does not parse.
        """
        view = body.get("view") or {}
        try:
            metadata = json.loads(view.get("private_metadata") or "")
        except ValueError:
            self._log.warning("Ignoring a modal submission whose private_metadata does not parse")
            return None

        parsed = self._parse_action_value(metadata.get("value"))
        if parsed is None or not metadata.get("channel") or not metadata.get("thread_ts"):
            return None

        interruption_id, status = parsed
        reason = ((view.get("state") or {}).get("values", {}).get(REASON_BLOCK_ID, {}).get(REASON_INPUT_ID, {}) or {}).get("value")
        user = metadata.get("user")
        reply_context = {"channel": metadata["channel"], "thread_ts": metadata["thread_ts"]}
        if user:
            reply_context["user"] = user
        return InboundRequest(
            session_id=metadata["thread_ts"],
            request_id=f"{NAME}:{metadata['channel']}:{metadata['ts']}:{interruption_id}:{status}",
            requests=[AgentResumeRequestAny(decisions=[ResumeDecision(id=interruption_id, status=status, message=reason or None)])],
            agent=self._agent,
            user_id=user,
            group_id=metadata["channel"],
            reply_context=reply_context,
        )

    @classmethod
    def _parse_action_value(cls, value: Optional[str]) -> Optional[tuple[str, str]]:
        """Read a button's ``<interruption id>:<verb>`` value back into the pair it encodes.

        Split from the right: an interruption id may contain a colon, a verb never does.

        :param value: The pressed button's value.
        :return: The interruption id and the decision's status, or None when either is missing.
        """
        interruption_id, _, status = (value or "").rpartition(":")
        if not interruption_id or status not in DECISION_VERBS:
            cls._log.warning(f"Ignoring a press whose button value does not parse: {value!r}")
            return None
        return interruption_id, status

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

        requests, _ = AttachmentStorageManager.offload(
            thread_ts,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )
        requests.append(AgentRequestAny(name="body", content=body))

        return InboundRequest(
            session_id=thread_ts,
            request_id=f"{channel}:{body.get('ts')}",
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
    OVERFLOW_NOTICE = "{count} more question(s) did not fit in this message and cannot be answered here."
    DENY_COLLECTS_REASON = True

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

    async def deliver_paused(self, reply: AgentPausedReplyAny, reply_context: Dict[str, str]) -> None:
        """Post the pause with each question's controls directly beneath it.

        Posted in the run's own thread, unlike :meth:`deliver`: a press carries the pause
        message's ``thread_ts`` as its session id, so moving it would resume the wrong session.

        :param reply: The paused reply to draw.
        :param reply_context: The delivery coordinates resolved at the edge.
        """
        client = self._client()
        if reply_context.get("ack_ts"):
            await client.chat_update(
                channel=reply_context.get("ack_channel") or reply_context["channel"],
                ts=reply_context["ack_ts"],
                text=f"Hi <@{reply_context.get('user')}>,",
            )

        await client.chat_postMessage(
            channel=reply_context["channel"],
            thread_ts=reply_context.get("thread_ts"),
            text="Approval needed",
            blocks=self._pause_blocks(reply),
        )

    def _pause_blocks(self, reply: AgentPausedReplyAny) -> list:
        """The pause as Block Kit: every question followed by whatever answers it.

        Slack takes 50 blocks per message. Two are held back for the closing line and a possible
        overflow notice; questions past what is left are counted rather than dropped silently.

        :param reply: The paused reply to draw.
        :return: The blocks to post.
        """
        opening, closing = self._pause_template(reply)
        blocks = self.split_reply(opening.strip())
        budget = MAX_BLOCKS - 2
        skipped = 0

        for interruption in reply.interruptions:
            question = self._question_blocks(interruption)
            if len(blocks) + len(question) > budget:
                skipped += 1
                continue
            blocks.extend(question)

        if skipped:
            self._log.warning(f"{skipped} interruption(s) did not fit Slack's {MAX_BLOCKS}-block message and were left out")
            blocks.append(self._notice(self.OVERFLOW_NOTICE.format(count=skipped)))
        blocks.extend(self.split_reply(closing.strip()))
        return blocks

    def _question_blocks(self, interruption: PausedInterruption) -> list:
        """One question, and the controls or the note that goes under it.

        A note stands in when :meth:`_decidable` rejects the question, or when its id would blow
        Slack's ``block_id``/``value`` budget — which costs the **whole** message, not one row.

        :param interruption: The question to draw.
        :return: Its section blocks, followed by its actions block or its note.
        """
        blocks = self.split_reply(self._format_interruption(interruption))
        if not self._decidable(interruption):
            blocks.append(self._notice(self.TYPED_ANSWER_NOTICE))
            return blocks

        block_id = f"{BLOCK_PREFIX}{interruption.id}"
        longest_value = max((len(f"{interruption.id}:{verb}") for verb in self.DECISIONS), default=0)
        if len(block_id) > BLOCK_ID_LIMIT or longest_value > VALUE_LIMIT:
            self._log.warning(
                f"Interruption '{interruption.id}' needs a {len(block_id)}-character block_id and a "
                f"{longest_value}-character value, over Slack's {BLOCK_ID_LIMIT}/{VALUE_LIMIT}; rendering it without buttons"
            )
            blocks.append(self._notice(self.UNPRESSABLE_NOTICE))
            return blocks

        blocks.append({"type": "actions", "block_id": block_id, "elements": [self._button(interruption.id, verb) for verb in self.DECISIONS]})
        return blocks

    @staticmethod
    def _notice(text: str) -> dict:
        """A line of small print, placed under the question it is about.

        :param text: What it says.
        :return: The context block to append.
        """
        return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}

    def _button(self, interruption_id: str, verb: str) -> dict:
        """One decision button. ``value`` is the payload; ``action_id`` only selects the listener.

        A denial carries :data:`REASON_PREFIX` when this adapter collects reasons, which is what
        tells the press handler to open a modal rather than record the decision outright.

        :param interruption_id: The interruption this button answers.
        :param verb: The decision it records.
        :return: The Block Kit button element.
        """
        prefix = REASON_PREFIX if verb == "denied" and self.DENY_COLLECTS_REASON else ACTION_PREFIX
        button = {
            "type": "button",
            "action_id": f"{prefix}{verb}",
            "text": {"type": "plain_text", "text": BUTTON_LABELS[verb]},
            "value": f"{interruption_id}:{verb}",
        }
        if verb in BUTTON_STYLES:
            button["style"] = BUTTON_STYLES[verb]
        return button

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
