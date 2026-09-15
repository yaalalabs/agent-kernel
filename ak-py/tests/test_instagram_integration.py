"""Instagram adapter: webhook delivery -> InboundRequest, and agent reply -> Send API calls."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.integration.instagram.adapter import InstagramInboundAdapter, InstagramOutboundAdapter
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

APP_SECRET = "app-secret"
SENDER = "igsid-123"


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_INSTAGRAM__ACCESS_TOKEN", "token")
    monkeypatch.setenv("AK_INSTAGRAM__VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("AK_INSTAGRAM__APP_SECRET", APP_SECRET)
    monkeypatch.setenv("AK_INSTAGRAM__AGENT", "helper")
    AKConfig._reset()
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    yield
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    AKConfig._reset()


def _api_stub():
    api = MagicMock()
    api.send_message = AsyncMock()
    api.sender_action = AsyncMock()
    api.download_attachment = AsyncMock(return_value=("ZmFrZQ==", "photo.jpg", "image/jpeg"))
    return api


def _inbound():
    adapter = InstagramInboundAdapter()
    adapter._api = _api_stub()
    return adapter


def _outbound():
    adapter = InstagramOutboundAdapter()
    adapter._api = _api_stub()
    return adapter


def _delivery(*events):
    return {"object": "instagram", "entry": [{"messaging": list(events)}]}


def _message_event(text="hello", mid="mid.1", attachments=None):
    message = {"mid": mid, "text": text}
    if attachments:
        message["attachments"] = attachments
    return {"sender": {"id": SENDER}, "message": message}


def _fake_request(body, headers=None, query=None):
    payload = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
    request = MagicMock()
    request.headers = headers or {}
    request.query_params = query or {}
    request.body = AsyncMock(return_value=payload)
    request.json = AsyncMock(return_value=json.loads(payload) if payload else {})
    return request


class TestParse:
    @pytest.mark.asyncio
    async def test_a_text_message_becomes_a_normalized_request(self):
        [request] = (await _inbound().parse(_fake_request(_delivery(_message_event())))).requests

        assert request.prompt == "hello"
        assert request.agent == "helper"
        # Instagram has no thread: the Instagram-scoped user is the conversation.
        assert request.session_id == SENDER
        assert request.user_id == SENDER
        assert request.request_id == "mid.1", "the platform message id dedupes a retry"
        assert request.reply_context == {"recipient_id": SENDER}
        assert isinstance(request.requests[0], AgentRequestText)

    @pytest.mark.asyncio
    async def test_every_event_in_one_delivery_is_parsed(self):
        delivery = _delivery(_message_event(text="first", mid="mid.1"), _message_event(text="second", mid="mid.2"))

        result = await _inbound().parse(_fake_request(delivery))

        assert [r.prompt for r in result.requests] == ["first", "second"]

    @pytest.mark.asyncio
    async def test_a_postback_is_read_as_its_title(self):
        event = {"sender": {"id": SENDER}, "postback": {"title": "Get started", "payload": "START"}}

        [request] = (await _inbound().parse(_fake_request(_delivery(event)))).requests

        assert request.prompt == "Get started"
        # A postback carries no mid, so the payload is what separates one press from the next.
        assert request.request_id == f"instagram:{SENDER}:START"

    @pytest.mark.asyncio
    async def test_read_receipts_and_reactions_are_not_messages(self):
        events = [{"sender": {"id": SENDER}, "read": {"watermark": 1}}, {"sender": {"id": SENDER}, "reaction": {"emoji": "❤️"}}]
        assert (await _inbound().parse(_fake_request(_delivery(*events)))).requests == []

    @pytest.mark.asyncio
    async def test_our_own_echoed_message_is_skipped(self):
        """Instagram echoes the bot's own sends back to it; answering one would loop."""
        event = {"sender": {"id": SENDER}, "message": {"mid": "mid.1", "text": "agent says hi", "is_echo": True}}
        assert (await _inbound().parse(_fake_request(_delivery(event)))).requests == []

    @pytest.mark.asyncio
    async def test_an_empty_message_is_ignored(self):
        assert (await _inbound().parse(_fake_request(_delivery(_message_event(text=""))))).requests == []

    @pytest.mark.asyncio
    async def test_a_foreign_object_type_is_ignored(self):
        assert (await _inbound().parse(_fake_request({"object": "page", "entry": []}))).requests == []

    @pytest.mark.asyncio
    async def test_an_image_attachment_travels_as_a_stored_reference(self, monkeypatch):
        monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
        monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
        AKConfig._reset()
        event = _message_event(attachments=[{"type": "image", "payload": {"url": "https://cdn.ig/photo.jpg"}}])

        [request] = (await _inbound().parse(_fake_request(_delivery(event)))).requests

        assert [r.type for r in request.requests] == ["text", "attachment_ref"]

    @pytest.mark.asyncio
    async def test_an_attachment_failure_leaves_nothing_to_run(self):
        """Instagram, unlike Messenger, has never told the agent about a failed attachment."""
        adapter = _inbound()
        adapter._api.download_attachment = AsyncMock(side_effect=RuntimeError("cdn down"))
        event = _message_event(text="", attachments=[{"type": "image", "payload": {"url": "https://cdn.ig/photo.jpg"}}])

        assert (await adapter.parse(_fake_request(_delivery(event)))).requests == []


class TestVerification:
    @pytest.mark.asyncio
    async def test_a_valid_signature_passes(self):
        body = json.dumps(_delivery(_message_event())).encode()
        signature = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        await _inbound().verify(_fake_request(body, headers={"x-hub-signature-256": signature}))

    @pytest.mark.asyncio
    async def test_a_bad_signature_is_a_403(self):
        with pytest.raises(HTTPException) as excinfo:
            await _inbound().verify(_fake_request(b"{}", headers={"x-hub-signature-256": "sha256=deadbeef"}))
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_the_subscription_handshake_echoes_the_challenge(self):
        request = _fake_request(b"", query={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "271828"})
        assert await _inbound().challenge(request) == 271828


class TestDeliver:
    @pytest.mark.asyncio
    async def test_the_reply_stops_the_typing_indicator_first(self):
        adapter = _outbound()

        await adapter.deliver(AgentReplyText(response="agent says hi"), {"recipient_id": SENDER})

        assert adapter._api.sender_action.await_args.args == (SENDER, "typing_off")
        assert adapter._api.send_message.await_args.args == (SENDER, ["agent says hi"])

    @pytest.mark.asyncio
    async def test_a_long_reply_is_split_at_the_instagram_limit(self):
        adapter = _outbound()

        await adapter.deliver(AgentReplyText(response="x" * 2500), {"recipient_id": SENDER})

        assert [len(c) for c in adapter._api.send_message.await_args.args[1]] == [1000, 1000, 500]

    @pytest.mark.asyncio
    async def test_the_acknowledgement_marks_seen_and_starts_typing(self):
        adapter = _outbound()

        assert await adapter.acknowledge({"recipient_id": SENDER}) == {}

        assert [call.args for call in adapter._api.sender_action.await_args_list] == [(SENDER, "mark_seen"), (SENDER, "typing_on")]

    @pytest.mark.asyncio
    async def test_an_error_reaches_the_user(self):
        adapter = _outbound()
        await adapter.deliver_error("Sorry, something broke.", {"recipient_id": SENDER})
        assert adapter._api.send_message.await_args.args == (SENDER, ["Sorry, something broke."])


class TestRoute:
    def test_a_signed_delivery_is_enqueued(self):
        transport = InMemoryTransport()
        handler = WebhookRESTRequestHandler(_inbound(), producer=IntegrationProducer(transport))
        app = FastAPI()
        app.include_router(handler.get_router())
        body = json.dumps(_delivery(_message_event())).encode()
        signature = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()

        response = TestClient(app).post("/instagram/webhook", content=body, headers={"x-hub-signature-256": signature})

        assert response.status_code == 200
        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)
        assert message.attributes["integration"] == "instagram"
        assert message.attributes["reply_recipient_id"] == SENDER
