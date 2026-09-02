"""Gmail inbound/outbound adapter pair (spec #524 §9).

Gmail is the only pulled integration: there is no webhook to receive, so the inbound half is a
:class:`PollingInboundAdapter` hosted by ``PollerRunner`` in its own process, at one replica.

Marking a message read still happens after the reply is sent, which is why the poller keeps an
in-process record of what it has already handed to the queue: until the reply goes out, the
message is still unread and the next poll would pick it up again.
"""

import base64
import logging
import os
import pickle
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Set

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequest, AgentRequestFile, AgentRequestImage, AgentRequestText
from ...core.multimodal.storage.offload import offload_attachments
from ..adapter.base import ATTACHMENTS_DISABLED_ERROR, SESSION_CACHE_ERROR, InboundParseResult, InboundRequest, OutboundAdapter, PollingInboundAdapter

NAME = "gmail"
MAX_RESULTS = 10
MAX_THREAD_HISTORY = 5

# Gmail API scopes needed to read, send and mark messages.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

DOCUMENT_MIME_TYPES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
EXTENSION_MIME_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

_log = logging.getLogger("ak.integration.gmail")


class _GmailService:
    """OAuth2 credentials and the Gmail client both halves use."""

    def __init__(self):
        self._token_file = AKConfig.get().gmail.token_file or "token.pickle"
        self._client_id = os.environ.get("AK_GMAIL__CLIENT_ID")
        self._client_secret = os.environ.get("AK_GMAIL__CLIENT_SECRET")
        self._redirect_uris = os.environ.get("AK_GMAIL__REDIRECT_URIS", "http://localhost").split(",")
        if not (self._client_id and self._client_secret):
            _log.error("Gmail credentials are not configured. Please set AK_GMAIL__CLIENT_ID and AK_GMAIL__CLIENT_SECRET.")
            raise ValueError("Incomplete Gmail configuration.")
        self._service = None

    @property
    def client(self):
        """The Gmail API client, authenticating on first use. None in test mode."""
        if self._service is None:
            self.authenticate()
        return self._service

    def authenticate(self) -> None:
        """Authenticate with the Gmail API using OAuth2.

        Skipped when AK_TEST_MODE=1, which leaves the client unset so every call short-circuits.
        """
        if os.environ.get("AK_TEST_MODE") == "1":
            _log.info("Test mode enabled: Skipping Gmail authentication.")
            self._service = None
            return

        creds = None
        if os.path.exists(self._token_file):
            with open(self._token_file, "rb") as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                _log.info("Refreshing expired credentials...")
                creds.refresh(Request())
            else:
                _log.info("Starting OAuth2 flow with environment variables...")
                client_config = {
                    "installed": {
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "redirect_uris": self._redirect_uris,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
                creds = InstalledAppFlow.from_client_config(client_config, SCOPES).run_local_server(port=0)

            with open(self._token_file, "wb") as token:
                pickle.dump(creds, token)
            _log.info(f"Credentials saved to {self._token_file}")

        self._service = build("gmail", "v1", credentials=creds)
        _log.info("Gmail API authentication successful")


class GmailInboundAdapter(PollingInboundAdapter):
    """Unread mail -> normalized requests."""

    name = NAME

    _log = _log

    def __init__(self):
        config = AKConfig.get().gmail
        self._agent = config.agent or None
        self.poll_interval = config.poll_interval or 30
        self._label_filter = config.label_filter or "INBOX"
        self._service = _GmailService()

        # Optional allow-lists, comma separated.
        sender_filter = os.environ.get("AK_GMAIL__SENDER_FILTER")
        subject_filter = os.environ.get("AK_GMAIL__SUBJECT_FILTER")
        self._allowed_senders = [s.strip() for s in sender_filter.split(",")] if sender_filter else None
        self._subject_keywords = [s.strip() for s in subject_filter.split(",")] if subject_filter else None

        # A message stays unread until its reply is sent, so without this the next poll would
        # enqueue it again. This is why the poller runs at a single replica.
        self._handled: Set[str] = set()

    def authenticate(self) -> None:
        """Authenticate eagerly, so a bad token fails at startup rather than on the first poll."""
        self._service.authenticate()

    async def poll(self) -> List[Any]:
        """Return the ids of unread messages that pass the filters and have not been handled."""
        client = self._service.client
        if client is None:
            self._log.info("Test mode: Skipping email check.")
            return []

        query = f"is:unread label:{self._label_filter}"
        self._log.info(f"[POLLING] Checking for emails with query: {query}")
        results = client.users().messages().list(userId="me", q=query, maxResults=MAX_RESULTS).execute()
        messages = results.get("messages", [])
        if not messages:
            self._log.info("[POLLING] No new unread emails found")
            return []

        self._log.info(f"[POLLING] Found {len(messages)} unread email(s)")
        pending = []
        for message in messages:
            message_id = message["id"]
            if message_id in self._handled:
                self._log.debug(f"Email {message_id} already handled, skipping")
                continue
            if not self._passes_filters(message_id):
                self._log.debug(f"Email {message_id} filtered out by sender or subject filter")
                # Marked handled so the filter is not re-evaluated every interval.
                self._handled.add(message_id)
                continue
            pending.append(message_id)
        return pending

    def mark_handled(self, raw: Any) -> None:
        self._handled.add(raw)

    async def parse(self, raw: Any) -> InboundParseResult:
        """Turn one unread message into a request, with its thread history and attachments."""
        client = self._service.client
        if client is None:
            self._log.info("Test mode: Skipping email processing.")
            return InboundParseResult()

        message_id = raw
        message = client.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = message["payload"]["headers"]
        subject = self._header(headers, "Subject")
        sender = self._header(headers, "From")
        message_id_header = self._header(headers, "Message-ID")  # for In-Reply-To/References threading
        thread_id = message.get("threadId")

        body = self._body(message["payload"])
        if not body:
            self._log.warning(f"Email {message_id} has no body content")
            return InboundParseResult()

        self._log.info(f"[EMAIL] Processing email - from={sender}, subject={subject}, thread_id={thread_id}, message_id={message_id}")

        attachments = self._attachments(message_id, message["payload"])
        if attachments:
            self._log.info(f"[EMAIL] Found {len(attachments)} attachment(s)")

        # The thread is the conversation; a message outside one falls back to the sender.
        session_id = thread_id or sender
        history = self._thread_history(thread_id, message_id)
        prompt = (
            f"Thread history:\n{history}\n\nNew message:\nFrom: {sender}\nSubject: {subject}\n\n{body}"
            if history
            else f"From: {sender}\nSubject: {subject}\n\n{body}"
        )

        requests: List[AgentRequest] = [AgentRequestText(prompt=prompt), *attachments]
        requests, _ = offload_attachments(
            session_id,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )

        return InboundParseResult(
            requests=[
                InboundRequest(
                    session_id=session_id,
                    request_id=message_id,
                    requests=requests,
                    prompt=prompt,
                    agent=self._agent,
                    user_id=sender,
                    reply_context={
                        "to": sender or "",
                        "subject": subject or "",
                        "thread_id": thread_id or "",
                        "message_id": message_id,
                        "in_reply_to": message_id_header or "",
                    },
                )
            ]
        )

    def _passes_filters(self, message_id: str) -> bool:
        """Whether the message's sender and subject match the configured allow-lists."""
        if not self._allowed_senders and not self._subject_keywords:
            return True
        try:
            message = self._service.client.users().messages().get(userId="me", id=message_id, format="full").execute()
            headers = message["payload"]["headers"]
            sender = self._header(headers, "From") or ""
            subject = self._header(headers, "Subject") or ""

            if self._allowed_senders and not any(allowed in sender for allowed in self._allowed_senders):
                self._log.debug(f"Email from '{sender}' does not match allowed senders filter")
                return False
            if self._subject_keywords and not any(keyword.lower() in subject.lower() for keyword in self._subject_keywords):
                self._log.debug(f"Subject '{subject}' does not contain any keywords filter")
                return False
            return True
        except Exception as e:
            # A filter that cannot be evaluated must not silently swallow the mail.
            self._log.warning(f"Error checking email filters: {e}")
            return True

    def _thread_history(self, thread_id: Optional[str], current_message_id: str) -> str:
        """The recent messages in the same thread, oldest first, excluding the current one."""
        if not thread_id:
            return ""
        try:
            thread = self._service.client.users().threads().get(userId="me", id=thread_id, format="full").execute()
            messages = sorted(thread.get("messages", []), key=lambda m: int(m.get("internalDate", "0")))
            history = []
            for message in messages:
                if message["id"] == current_message_id:
                    continue
                headers = message["payload"]["headers"]
                body = self._body(message["payload"])
                if body:
                    history.append(
                        f"From: {self._header(headers, 'From')}\nDate: {self._header(headers, 'Date')}\n"
                        f"Subject: {self._header(headers, 'Subject')}\n\n{body}\n{'-' * 40}"
                    )
            return "\n".join(history[-MAX_THREAD_HISTORY:])
        except Exception as e:
            self._log.warning(f"Error fetching thread history: {e}")
            return ""

    @staticmethod
    def _header(headers: list, name: str) -> Optional[str]:
        """Read one header value, case-insensitively."""
        for header in headers:
            if header["name"].lower() == name.lower():
                return header["value"]
        return None

    def _body(self, payload: dict) -> str:
        """Extract the message body: plain text first, then HTML, recursing into multiparts."""
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")
                data = part.get("body", {}).get("data", "")
                if mime_type == "text/plain" and data:
                    decoded = self._decode(data, "plain text")
                    if decoded:
                        return decoded
                elif mime_type == "text/html" and data and not body:
                    body = self._decode(data, "HTML")
                elif mime_type.startswith("multipart/") and not body:
                    nested = self._body(part)
                    if nested:
                        return nested
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                body = self._decode(data, "message body")
        return body.strip() if body else ""

    def _decode(self, data: str, what: str) -> str:
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8")
        except Exception as e:
            self._log.warning(f"Error decoding {what}: {e}")
            return ""

    def _attachments(self, message_id: str, payload: dict) -> List[AgentRequest]:
        """Download the message's attachments as image/file requests."""
        attachments: List[AgentRequest] = []
        try:
            for part in payload.get("parts", []):
                filename = part.get("filename")
                if not filename:
                    continue  # an inline/text part, not an attachment
                if not part.get("partId"):
                    continue
                try:
                    data = (
                        self._service.client.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=message_id, id=part.get("body", {}).get("attachmentId"))
                        .execute()
                    )
                    if "data" not in data:
                        self._log.warning(f"No data in attachment: {filename}")
                        continue
                    # Gmail returns URL-safe base64; downstream consumers expect standard base64.
                    encoded = base64.b64encode(base64.urlsafe_b64decode(data["data"])).decode("utf-8")
                    mime_type = self._attachment_mime_type(part.get("mimeType", "application/octet-stream"), filename)

                    if mime_type.startswith("image/"):
                        attachments.append(AgentRequestImage(image_data=encoded, name=filename, mime_type=mime_type))
                    elif mime_type in DOCUMENT_MIME_TYPES:
                        attachments.append(AgentRequestFile(file_data=encoded, name=filename, mime_type=mime_type))
                    else:
                        self._log.debug(f"Skipping unsupported attachment type: {mime_type}")
                except Exception as e:
                    self._log.warning(f"Error extracting attachment {filename}: {e}")
            if attachments:
                self._log.info(f"Extracted {len(attachments)} attachment(s) from message {message_id}")
        except Exception as e:
            self._log.warning(f"Error processing attachments: {e}")
        return attachments

    def _attachment_mime_type(self, declared: str, filename: str) -> str:
        """Infer a usable MIME type when Gmail declares only the generic one."""
        if declared and declared != "application/octet-stream":
            return declared
        extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        inferred = EXTENSION_MIME_TYPES.get(extension)
        if inferred:
            self._log.info(f"Inferred MIME type for {filename}: {inferred} (from extension .{extension})")
            return inferred
        self._log.warning(f"Could not infer MIME type for extension .{extension}")
        return declared


class GmailOutboundAdapter(OutboundAdapter):
    """Agent replies -> threaded email replies."""

    name = NAME

    _log = _log

    def __init__(self):
        self._service = _GmailService()

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        """Send the reply into the original thread, then mark the message read.

        The order matters: an unread message is what the poller picks up, so marking it read
        before the reply lands would lose the mail if the send failed.
        """
        self._send(str(reply), reply_context)

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        try:
            self._send(message, reply_context)
        except Exception as e:
            self._log.error(f"Could not deliver the Gmail error message: {e}")

    def _send(self, text: str, reply_context: Dict[str, str]) -> None:
        """Compose and send one threaded reply, then take the original out of the unread query."""
        client = self._service.client
        if client is None:
            self._log.info("Test mode: Skipping send reply.")
            return

        thread_id = reply_context.get("thread_id") or None
        message = MIMEText(self._with_signature(text))
        message["to"] = reply_context["to"]
        message["subject"] = reply_context.get("subject", "")
        in_reply_to = reply_context.get("in_reply_to")
        if in_reply_to:
            # Both headers: Gmail links the messages in the thread on References.
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to

        payload = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")}
        if thread_id:
            payload["threadId"] = thread_id

        self._log.info(f"[SEND_REPLY] Sending reply with threadId={thread_id}, to={message['to']}, subject={message['subject']}")
        result = client.users().messages().send(userId="me", body=payload).execute()
        self._log.info(f"[SEND_REPLY] Reply sent successfully (message ID: {result['id']}, threadId: {thread_id})")

        self._mark_read(reply_context.get("message_id"))

    @staticmethod
    def _with_signature(body: str) -> str:
        """Append the configured sign-off and name, when either is set."""
        client_name = os.environ.get("AK_CLIENT_NAME")
        sign_off = os.environ.get("AK_GMAIL_SIGN_OFF")
        lines = []
        if sign_off:
            lines.append(f"{sign_off}," if client_name else sign_off)
        if client_name:
            lines.append(client_name)
        return f"{body}\n\n" + "\n".join(lines) if lines else body

    def _mark_read(self, message_id: Optional[str]) -> None:
        """Take the message out of the unread query the poller runs."""
        if not message_id:
            return
        try:
            self._service.client.users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
        except Exception as e:
            self._log.warning(f"Error marking email as read: {e}")
