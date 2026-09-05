"""Gmail adapter: unread mail -> InboundRequest, and agent reply -> a threaded reply."""

import base64
from unittest.mock import MagicMock

import pytest

pytest.importorskip("googleapiclient")

from agentkernel.core.config import AKConfig  # noqa: E402
from agentkernel.core.model import AgentReplyText, AgentRequestText  # noqa: E402
from agentkernel.integration.adapter.base import Source  # noqa: E402
from agentkernel.integration.gmail.adapter import GmailInboundAdapter, GmailOutboundAdapter, _GmailService  # noqa: E402

SENDER = "alice@example.com"
THREAD_ID = "thread-1"
MESSAGE_ID = "msg-1"


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_GMAIL__CLIENT_ID", "client-id")
    monkeypatch.setenv("AK_GMAIL__CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("AK_GMAIL__SENDER_FILTER", raising=False)
    monkeypatch.delenv("AK_GMAIL__SUBJECT_FILTER", raising=False)
    monkeypatch.delenv("AK_CLIENT_NAME", raising=False)
    monkeypatch.delenv("AK_GMAIL_SIGN_OFF", raising=False)
    AKConfig._reset()
    yield
    AKConfig._reset()


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _message(message_id=MESSAGE_ID, body="Hello agent", subject="Greetings", thread_id=THREAD_ID, parts=None):
    payload = {
        "headers": [
            {"name": "From", "value": SENDER},
            {"name": "Subject", "value": subject},
            {"name": "Message-ID", "value": "<orig@mail>"},
            {"name": "Date", "value": "Mon, 1 Sep 2025 10:00:00 +0000"},
        ],
        "body": {"data": _encode(body)},
    }
    if parts is not None:
        payload["parts"] = parts
        payload.pop("body")
    return {"id": message_id, "threadId": thread_id, "internalDate": "1000", "payload": payload}


def _service(messages=None, listed=None, thread=None):
    """A Gmail client stub shaped like the discovery-built service."""
    messages = messages or {MESSAGE_ID: _message()}
    client = MagicMock()
    users = client.users.return_value
    users.messages.return_value.list.return_value.execute.return_value = {"messages": listed if listed is not None else [{"id": MESSAGE_ID}]}
    users.messages.return_value.get.side_effect = lambda userId, id, format: MagicMock(execute=lambda: messages[id])
    users.threads.return_value.get.return_value.execute.return_value = thread or {"messages": []}
    users.messages.return_value.send.return_value.execute.return_value = {"id": "sent-1"}
    return client


def _gmail_service(client):
    service = object.__new__(_GmailService)
    service._token_file = "token.pickle"
    service._client_id = "client-id"
    service._client_secret = "client-secret"
    service._redirect_uris = ["http://localhost"]
    service._service = client
    return service


def _inbound(client=None, agent="helper", allowed_senders=None, subject_keywords=None):
    adapter = object.__new__(GmailInboundAdapter)
    adapter._agent = agent
    adapter.poll_interval = 30
    adapter._label_filter = "INBOX"
    adapter._service = _gmail_service(client if client is not None else _service())
    adapter._allowed_senders = allowed_senders
    adapter._subject_keywords = subject_keywords
    adapter._handled = set()
    return adapter


def _outbound(client=None):
    adapter = object.__new__(GmailOutboundAdapter)
    adapter._service = _gmail_service(client if client is not None else _service())
    return adapter


def test_gmail_is_the_only_polled_integration():
    assert GmailInboundAdapter.source is Source.POLLER
    assert not GmailInboundAdapter.webhook_path


class TestPoll:
    @pytest.mark.asyncio
    async def test_unread_messages_are_returned(self):
        assert await _inbound().poll() == [MESSAGE_ID]

    @pytest.mark.asyncio
    async def test_an_already_handled_message_is_not_returned_again(self):
        """A message stays unread until its reply is sent, so the guard is what stops a re-run."""
        adapter = _inbound()
        adapter.mark_handled(MESSAGE_ID)
        assert await adapter.poll() == []

    @pytest.mark.asyncio
    async def test_an_empty_inbox_returns_nothing(self):
        assert await _inbound(client=_service(listed=[])).poll() == []

    @pytest.mark.asyncio
    async def test_a_sender_outside_the_allow_list_is_filtered_out(self):
        adapter = _inbound(allowed_senders=["bob@example.com"])
        assert await adapter.poll() == []
        # Marked handled so the filter is not re-evaluated on every interval.
        assert MESSAGE_ID in adapter._handled

    @pytest.mark.asyncio
    async def test_a_matching_subject_keyword_passes(self):
        assert await _inbound(subject_keywords=["greet"]).poll() == [MESSAGE_ID]

    @pytest.mark.asyncio
    async def test_test_mode_polls_nothing(self):
        adapter = _inbound(client=None)
        adapter._service._service = None
        adapter._service.authenticate = lambda: None
        assert await adapter.poll() == []


class TestParse:
    @pytest.mark.asyncio
    async def test_an_email_becomes_a_normalized_request(self):
        [request] = (await _inbound().parse(MESSAGE_ID)).requests

        assert request.prompt == f"From: {SENDER}\nSubject: Greetings\n\nHello agent"
        assert request.agent == "helper"
        # The Gmail thread is the conversation.
        assert request.session_id == THREAD_ID
        assert request.user_id == SENDER
        assert request.request_id == MESSAGE_ID
        assert isinstance(request.requests[0], AgentRequestText)

    @pytest.mark.asyncio
    async def test_the_reply_context_carries_everything_the_send_needs(self):
        [request] = (await _inbound().parse(MESSAGE_ID)).requests

        assert request.reply_context == {
            "to": SENDER,
            "subject": "Greetings",
            "thread_id": THREAD_ID,
            "message_id": MESSAGE_ID,
            "in_reply_to": "<orig@mail>",
        }

    @pytest.mark.asyncio
    async def test_the_session_falls_back_to_the_sender_without_a_thread(self):
        client = _service(messages={MESSAGE_ID: _message(thread_id=None)})
        [request] = (await _inbound(client=client).parse(MESSAGE_ID)).requests
        assert request.session_id == SENDER

    @pytest.mark.asyncio
    async def test_thread_history_is_prepended_oldest_first(self):
        thread = {
            "messages": [
                {
                    "id": "older",
                    "internalDate": "1",
                    "payload": {
                        "headers": [{"name": "From", "value": SENDER}, {"name": "Subject", "value": "Greetings"}, {"name": "Date", "value": "Sun"}],
                        "body": {"data": _encode("earlier note")},
                    },
                },
                _message(),
            ]
        }
        client = _service(thread=thread)

        [request] = (await _inbound(client=client).parse(MESSAGE_ID)).requests

        assert request.prompt.startswith("Thread history:")
        assert "earlier note" in request.prompt
        assert "New message:" in request.prompt

    @pytest.mark.asyncio
    async def test_a_body_less_email_is_ignored(self):
        client = _service(messages={MESSAGE_ID: _message(body="")})
        assert (await _inbound(client=client).parse(MESSAGE_ID)).requests == []

    @pytest.mark.asyncio
    async def test_a_multipart_email_prefers_plain_text(self):
        parts = [
            {"mimeType": "text/html", "body": {"data": _encode("<p>html</p>")}},
            {"mimeType": "text/plain", "body": {"data": _encode("plain body")}},
        ]
        client = _service(messages={MESSAGE_ID: _message(parts=parts)})

        [request] = (await _inbound(client=client).parse(MESSAGE_ID)).requests

        assert request.prompt.endswith("plain body")

    @pytest.mark.asyncio
    async def test_an_attachment_travels_as_a_stored_reference(self, monkeypatch):
        monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
        monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
        AKConfig._reset()
        parts = [
            {"mimeType": "text/plain", "filename": "", "body": {"data": _encode("see attached")}},
            {"mimeType": "application/pdf", "filename": "report.pdf", "partId": "1", "body": {"attachmentId": "att-1"}},
        ]
        client = _service(messages={MESSAGE_ID: _message(parts=parts)})
        client.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {"data": _encode("%PDF")}

        [request] = (await _inbound(client=client).parse(MESSAGE_ID)).requests

        assert [r.type for r in request.requests] == ["text", "attachment_ref"]

    @pytest.mark.asyncio
    async def test_test_mode_parses_nothing(self):
        adapter = _inbound()
        adapter._service._service = None
        adapter._service.authenticate = lambda: None
        assert (await adapter.parse(MESSAGE_ID)).requests == []


class TestDeliver:
    def _sent(self, client):
        payload = client.users.return_value.messages.return_value.send.call_args.kwargs["body"]
        return payload, base64.urlsafe_b64decode(payload["raw"]).decode()

    def _context(self, **overrides):
        return {
            "to": SENDER,
            "subject": "Greetings",
            "thread_id": THREAD_ID,
            "message_id": MESSAGE_ID,
            "in_reply_to": "<orig@mail>",
            **overrides,
        }

    @pytest.mark.asyncio
    async def test_the_reply_stays_in_the_original_thread(self):
        client = _service()

        await _outbound(client).deliver(AgentReplyText(response="agent says hi"), self._context())

        payload, raw = self._sent(client)
        assert payload["threadId"] == THREAD_ID
        assert "In-Reply-To: <orig@mail>" in raw
        assert "References: <orig@mail>" in raw
        assert "agent says hi" in raw

    @pytest.mark.asyncio
    async def test_the_message_is_marked_read_only_after_the_reply_is_sent(self):
        """An unread message is what the poller picks up: marking it read first would lose it."""
        client = _service()

        await _outbound(client).deliver(AgentReplyText(response="hi"), self._context())

        modify = client.users.return_value.messages.return_value.modify
        assert modify.call_args.kwargs == {"userId": "me", "id": MESSAGE_ID, "body": {"removeLabelIds": ["UNREAD"]}}

    @pytest.mark.asyncio
    async def test_a_send_failure_leaves_the_message_unread_and_propagates(self):
        client = _service()
        client.users.return_value.messages.return_value.send.return_value.execute.side_effect = RuntimeError("gmail down")

        with pytest.raises(RuntimeError):
            await _outbound(client).deliver(AgentReplyText(response="hi"), self._context())

        client.users.return_value.messages.return_value.modify.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_signature_is_appended_when_configured(self, monkeypatch):
        monkeypatch.setenv("AK_GMAIL_SIGN_OFF", "Best regards")
        monkeypatch.setenv("AK_CLIENT_NAME", "Yaala")
        client = _service()

        await _outbound(client).deliver(AgentReplyText(response="hi"), self._context())

        _, raw = self._sent(client)
        assert "Best regards,\nYaala" in raw

    @pytest.mark.asyncio
    async def test_an_error_is_emailed_back(self):
        client = _service()

        await _outbound(client).deliver_error(GmailOutboundAdapter.ERROR_MESSAGE, self._context())

        _, raw = self._sent(client)
        assert GmailOutboundAdapter.ERROR_MESSAGE in raw

    @pytest.mark.asyncio
    async def test_an_error_delivery_failure_does_not_escape(self):
        client = _service()
        client.users.return_value.messages.return_value.send.return_value.execute.side_effect = RuntimeError("gmail down")

        await _outbound(client).deliver_error("boom", self._context())

    @pytest.mark.asyncio
    async def test_test_mode_sends_nothing(self):
        adapter = _outbound()
        client = adapter._service._service
        adapter._service._service = None
        adapter._service.authenticate = lambda: None

        await adapter.deliver(AgentReplyText(response="hi"), self._context())

        client.users.return_value.messages.return_value.send.assert_not_called()
