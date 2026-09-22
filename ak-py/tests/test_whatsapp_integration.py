"""WhatsApp adapter: webhook delivery -> InboundRequest, and agent reply -> Cloud API sends."""

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
from agentkernel.integration.whatsapp.adapter import WhatsAppInboundAdapter, WhatsAppOutboundAdapter, _WhatsAppClient
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

APP_SECRET = "app-secret"
FROM = "15551234567"


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_WHATSAPP__ACCESS_TOKEN", "token")
    monkeypatch.setenv("AK_WHATSAPP__PHONE_NUMBER_ID", "phone-1")
    monkeypatch.setenv("AK_WHATSAPP__VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("AK_WHATSAPP__APP_SECRET", APP_SECRET)
    AKConfig._reset()
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    yield
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    AKConfig._reset()


def _client_stub(app_secret=APP_SECRET, verify_token="verify-me"):
    client = object.__new__(_WhatsAppClient)
    client._access_token = "token"
    client._phone_number_id = "phone-1"
    client._verify_token = verify_token
    client._app_secret = app_secret
    client._base_url = "https://graph.facebook.com/v24.0"
    client.send_message = AsyncMock()
    client.media_info = AsyncMock(return_value=(1024, "image/jpeg"))
    client.download_media = AsyncMock(return_value="ZmFrZQ==")
    return client


def _inbound(agent="helper", max_file_size=10 * 1024 * 1024, **client_kwargs):
    adapter = object.__new__(WhatsAppInboundAdapter)
    adapter._agent = agent
    adapter._max_file_size = max_file_size
    adapter._client = _client_stub(**client_kwargs)
    return adapter


def _outbound(acknowledgement=None):
    adapter = object.__new__(WhatsAppOutboundAdapter)
    adapter._acknowledgement = acknowledgement
    adapter._client = _client_stub()
    return adapter


def _message(text="hello", message_id="wamid.1", message_type="text", **extra):
    message = {"id": message_id, "from": FROM, "type": message_type, **extra}
    if message_type == "text":
        message["text"] = {"body": text}
    return message


def _delivery(*messages, statuses=None):
    value = {"messages": list(messages)}
    if statuses:
        value["statuses"] = statuses
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": value}]}]}


class TestParse:
    @pytest.mark.asyncio
    async def test_a_text_message_becomes_a_normalized_request(self):
        result = await _inbound().parse(_fake_request(_delivery(_message())))

        [request] = result.requests
        assert request.prompt == "hello"
        assert request.agent == "helper"
        # WhatsApp has no thread: the sender's number is the conversation.
        assert request.session_id == FROM
        assert request.user_id == FROM
        assert request.request_id == "wamid.1", "the platform message id dedupes a retry"
        assert request.reply_context == {"to": FROM, "reply_to_message_id": "wamid.1"}
        assert isinstance(request.requests[0], AgentRequestText)

    @pytest.mark.asyncio
    async def test_every_message_in_one_delivery_is_parsed(self):
        """A single Meta webhook can carry several messages; none may be dropped."""
        delivery = _delivery(_message(text="first", message_id="wamid.1"), _message(text="second", message_id="wamid.2"))

        result = await _inbound().parse(_fake_request(delivery))

        assert [r.prompt for r in result.requests] == ["first", "second"]

    @pytest.mark.asyncio
    async def test_a_status_update_is_not_a_message(self):
        result = await _inbound().parse(_fake_request(_delivery(statuses=[{"status": "delivered"}])))
        assert result.requests == []

    @pytest.mark.asyncio
    async def test_a_foreign_object_type_is_ignored(self):
        result = await _inbound().parse(_fake_request({"object": "page", "entry": []}))
        assert result.requests == []

    @pytest.mark.asyncio
    async def test_a_button_reply_is_read_as_its_title(self):
        message = _message(message_type="interactive", interactive={"type": "button_reply", "button_reply": {"title": "Yes please"}})

        result = await _inbound().parse(_fake_request(_delivery(message)))

        assert result.requests[0].prompt == "Yes please"

    @pytest.mark.asyncio
    async def test_audio_and_video_are_refused_with_a_reply(self):
        adapter = _inbound()

        result = await adapter.parse(_fake_request(_delivery(_message(message_type="audio"))))

        assert result.requests == []
        adapter._client.send_message.assert_awaited_once()
        assert "audio and video" in adapter._client.send_message.await_args.args[1][0]

    @pytest.mark.asyncio
    async def test_an_oversized_image_is_refused_before_download(self):
        adapter = _inbound(max_file_size=10)
        adapter._client.media_info = AsyncMock(return_value=(5_000_000, "image/jpeg"))

        result = await adapter.parse(_fake_request(_delivery(_message(message_type="image", image={"id": "media-1"}))))

        assert result.requests == []
        adapter._client.download_media.assert_not_awaited()
        assert "exceeds the maximum allowed size" in adapter._client.send_message.await_args.args[1][0]

    @pytest.mark.asyncio
    async def test_a_download_failure_is_reported_to_the_sender(self):
        adapter = _inbound()
        adapter._client.download_media = AsyncMock(return_value=None)

        result = await adapter.parse(_fake_request(_delivery(_message(message_type="image", image={"id": "media-1"}))))

        assert result.requests == []
        assert "could not download" in adapter._client.send_message.await_args.args[1][0]

    @pytest.mark.asyncio
    async def test_an_image_travels_as_a_stored_reference(self, monkeypatch):
        monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
        monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
        AKConfig._reset()
        adapter = _inbound()

        result = await adapter.parse(_fake_request(_delivery(_message(message_type="image", image={"id": "media-1", "caption": "look"}))))

        [request] = result.requests
        assert request.prompt == "look"
        assert [r.type for r in request.requests] == ["text", "attachment_ref"]


class TestVerification:
    @pytest.mark.asyncio
    async def test_a_valid_signature_passes(self):
        body = json.dumps(_delivery(_message())).encode()
        signature = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        await _inbound().verify(_fake_request(body, headers={"x-hub-signature-256": signature}))

    @pytest.mark.asyncio
    async def test_a_bad_signature_is_a_403(self):
        with pytest.raises(HTTPException) as excinfo:
            await _inbound().verify(_fake_request(b"{}", headers={"x-hub-signature-256": "sha256=deadbeef"}))
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_a_missing_signature_is_a_403(self):
        with pytest.raises(HTTPException) as excinfo:
            await _inbound().verify(_fake_request(b"{}"))
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_app_secret_means_no_check(self):
        # The secret is optional in the platform config, and always has been.
        await _inbound(app_secret="").verify(_fake_request(b"{}"))

    @pytest.mark.asyncio
    async def test_the_subscription_handshake_echoes_the_challenge(self):
        request = _fake_request(b"", query={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "31415"})
        assert await _inbound().challenge(request) == 31415

    @pytest.mark.asyncio
    async def test_a_handshake_with_the_wrong_token_is_a_403(self):
        request = _fake_request(b"", query={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "31415"})
        with pytest.raises(HTTPException) as excinfo:
            await _inbound().challenge(request)
        assert excinfo.value.status_code == 403


class TestDeliver:
    @pytest.mark.asyncio
    async def test_the_reply_quotes_the_original_message(self):
        adapter = _outbound()

        await adapter.deliver(AgentReplyText(response="agent says hi"), {"to": FROM, "reply_to_message_id": "wamid.1"})

        to_number, chunks, reply_to = adapter._client.send_message.await_args.args
        assert (to_number, chunks, reply_to) == (FROM, ["agent says hi"], "wamid.1")

    @pytest.mark.asyncio
    async def test_a_long_reply_is_split(self):
        adapter = _outbound()

        await adapter.deliver(AgentReplyText(response="x" * 5000), {"to": FROM, "reply_to_message_id": "wamid.1"})

        chunks = adapter._client.send_message.await_args.args[1]
        assert [len(c) for c in chunks] == [4096, 904]

    @pytest.mark.asyncio
    async def test_the_acknowledgement_is_sent_when_configured(self):
        adapter = _outbound(acknowledgement="on it")

        assert await adapter.acknowledge({"to": FROM, "reply_to_message_id": "wamid.1"}) == {}

        assert adapter._client.send_message.await_args.args[1] == ["on it"]

    @pytest.mark.asyncio
    async def test_no_acknowledgement_is_sent_when_none_is_configured(self):
        adapter = _outbound()
        await adapter.acknowledge({"to": FROM})
        adapter._client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_error_reaches_the_user(self):
        adapter = _outbound()
        await adapter.deliver_error("Sorry, something broke.", {"to": FROM, "reply_to_message_id": "wamid.1"})
        assert adapter._client.send_message.await_args.args[1] == ["Sorry, something broke."]


class TestRoute:
    def test_a_signed_delivery_is_enqueued(self):
        transport = InMemoryTransport()
        handler = WebhookRESTRequestHandler(_inbound(), producer=IntegrationProducer(transport))
        app = FastAPI()
        app.include_router(handler.get_router())
        body = json.dumps(_delivery(_message())).encode()
        signature = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()

        response = TestClient(app).post("/whatsapp/webhook", content=body, headers={"x-hub-signature-256": signature})

        assert response.status_code == 200
        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)
        assert message.attributes["integration"] == "whatsapp"
        assert message.attributes["reply_to"] == FROM

    def test_an_unsigned_delivery_is_rejected_without_enqueueing(self):
        transport = InMemoryTransport()
        handler = WebhookRESTRequestHandler(_inbound(), producer=IntegrationProducer(transport))
        app = FastAPI()
        app.include_router(handler.get_router())

        assert TestClient(app).post("/whatsapp/webhook", json=_delivery(_message())).status_code == 403
        assert transport.create_consumer(QueueName.INPUT).fetch(1, 0.05) == []


def _fake_request(body, headers=None, query=None):
    """A minimal stand-in for the parts of a FastAPI Request the adapters touch."""
    payload = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
    request = MagicMock()
    request.headers = headers or {}
    request.query_params = query or {}
    request.body = AsyncMock(return_value=payload)
    request.json = AsyncMock(return_value=json.loads(payload) if payload else {})
    return request
