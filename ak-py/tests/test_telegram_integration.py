"""Telegram adapter: update -> InboundRequest, and agent reply -> Bot API sends."""

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
from agentkernel.integration.telegram.adapter import HELP_MESSAGE, START_MESSAGE, TelegramInboundAdapter, TelegramOutboundAdapter, _TelegramClient
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

SECRET = "webhook-secret"
CHAT_ID = 4242


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_TELEGRAM__BOT_TOKEN", "bot-token")
    monkeypatch.setenv("AK_TELEGRAM__WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("AK_TELEGRAM__AGENT", "helper")
    AKConfig._reset()
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    yield
    IntegrationAdapterFactory.reset()
    InMemoryTransport.reset()
    AKConfig._reset()


def _client_stub():
    client = object.__new__(_TelegramClient)
    client._bot_token = "bot-token"
    client._base_url = "https://api.telegram.org/botbot-token"
    client._webhook_secret = SECRET
    client.send_message = AsyncMock()
    client.chat_action = AsyncMock()
    client.answer_callback_query = AsyncMock()
    client.file_info = AsyncMock(return_value={"file_path": "photos/file_1.jpg", "file_size": 1024})
    client.download = AsyncMock(return_value=b"\x89PNG")
    return client


def _inbound(max_file_size=10 * 1024 * 1024):
    adapter = object.__new__(TelegramInboundAdapter)
    adapter._agent = "helper"
    adapter._max_file_size = max_file_size
    adapter._client = _client_stub()
    return adapter


def _outbound():
    adapter = object.__new__(TelegramOutboundAdapter)
    adapter._client = _client_stub()
    return adapter


def _update(text="hello", update_id=100, message_id=7, **extra):
    message = {"message_id": message_id, "chat": {"id": CHAT_ID}, "from": {"id": 99}, **extra}
    if text is not None:
        message["text"] = text
    return {"update_id": update_id, "message": message}


def _fake_request(body, headers=None):
    payload = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
    request = MagicMock()
    request.headers = headers or {}
    request.query_params = {}
    request.body = AsyncMock(return_value=payload)
    request.json = AsyncMock(return_value=json.loads(payload) if payload else {})
    return request


class TestParse:
    @pytest.mark.asyncio
    async def test_a_message_becomes_a_normalized_request(self):
        [request] = (await _inbound().parse(_fake_request(_update()))).requests

        assert request.prompt == "hello"
        assert request.agent == "helper"
        # The chat is the conversation.
        assert request.session_id == str(CHAT_ID)
        assert request.user_id == "99"
        assert request.reply_context == {"chat_id": str(CHAT_ID)}
        assert isinstance(request.requests[0], AgentRequestText)

    @pytest.mark.asyncio
    async def test_the_update_id_is_the_dedup_key(self):
        """The whole update is parsed, not just its message: update_id is what Telegram retries with."""
        [request] = (await _inbound().parse(_fake_request(_update(update_id=555)))).requests
        assert request.request_id == "555"

    @pytest.mark.asyncio
    async def test_a_media_caption_is_read_as_the_prompt(self, monkeypatch):
        monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
        monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
        AKConfig._reset()
        update = _update(text=None, caption="what is this", photo=[{"file_id": "f-small"}, {"file_id": "f-large"}])

        [request] = (await _inbound().parse(_fake_request(update))).requests

        assert request.prompt == "what is this"
        assert [r.type for r in request.requests] == ["text", "attachment_ref"]

    @pytest.mark.asyncio
    async def test_the_largest_photo_rendition_is_taken(self, monkeypatch):
        monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
        monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
        AKConfig._reset()
        adapter = _inbound()
        update = _update(text="look", photo=[{"file_id": "f-small"}, {"file_id": "f-large"}])

        await adapter.parse(_fake_request(update))

        adapter._client.file_info.assert_awaited_once_with("f-large")

    @pytest.mark.asyncio
    async def test_an_edited_message_is_treated_as_a_new_one(self):
        update = _update()
        update["edited_message"] = update.pop("message")

        [request] = (await _inbound().parse(_fake_request(update))).requests

        assert request.prompt == "hello"

    @pytest.mark.asyncio
    async def test_a_callback_query_is_read_as_its_data(self):
        adapter = _inbound()
        update = {
            "update_id": 101,
            "callback_query": {"id": "cb-1", "data": "option-a", "from": {"id": 99}, "message": {"chat": {"id": CHAT_ID}}},
        }

        [request] = (await adapter.parse(_fake_request(update))).requests

        assert request.prompt == "option-a"
        adapter._client.answer_callback_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_and_help_are_answered_without_running_the_agent(self):
        adapter = _inbound()

        assert (await adapter.parse(_fake_request(_update(text="/start")))).requests == []
        assert adapter._client.send_message.await_args.args[1] == [START_MESSAGE]

        assert (await adapter.parse(_fake_request(_update(text="/help")))).requests == []
        assert adapter._client.send_message.await_args.args[1] == [HELP_MESSAGE]

    @pytest.mark.asyncio
    async def test_an_unknown_command_still_reaches_the_agent(self):
        [request] = (await _inbound().parse(_fake_request(_update(text="/summarise")))).requests
        assert request.prompt == "/summarise"

    @pytest.mark.asyncio
    async def test_an_empty_message_is_ignored(self):
        assert (await _inbound().parse(_fake_request(_update(text="")))).requests == []

    @pytest.mark.asyncio
    async def test_an_unknown_update_type_is_ignored(self):
        assert (await _inbound().parse(_fake_request({"update_id": 1, "poll": {}}))).requests == []

    @pytest.mark.asyncio
    async def test_an_oversized_photo_is_skipped_before_download(self):
        adapter = _inbound(max_file_size=10)
        adapter._client.file_info = AsyncMock(return_value={"file_path": "photos/big.jpg", "file_size": 5_000_000})

        [request] = (await adapter.parse(_fake_request(_update(text="look", photo=[{"file_id": "f-1"}])))).requests

        adapter._client.download.assert_not_awaited()
        assert [r.type for r in request.requests] == ["text"]

    @pytest.mark.asyncio
    async def test_a_photo_that_grows_past_the_limit_is_skipped_after_download(self):
        """Telegram omits the size for some files, so the cap is re-checked on the bytes."""
        adapter = _inbound(max_file_size=2)
        adapter._client.file_info = AsyncMock(return_value={"file_path": "photos/unknown.jpg"})

        [request] = (await adapter.parse(_fake_request(_update(text="look", photo=[{"file_id": "f-1"}])))).requests

        assert [r.type for r in request.requests] == ["text"]


class TestVerification:
    @pytest.mark.asyncio
    async def test_the_configured_secret_token_is_required(self):
        with pytest.raises(HTTPException) as excinfo:
            await _inbound().verify(_fake_request(b"{}", headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}))
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_the_right_secret_token_passes(self):
        await _inbound().verify(_fake_request(b"{}", headers={"X-Telegram-Bot-Api-Secret-Token": SECRET}))

    @pytest.mark.asyncio
    async def test_no_secret_configured_means_no_check(self):
        adapter = _inbound()
        adapter._client._webhook_secret = ""
        await adapter.verify(_fake_request(b"{}"))

    def test_telegram_gets_its_own_success_shape(self):
        assert _inbound().success_response() == {"ok": True}


class TestDeliver:
    @pytest.mark.asyncio
    async def test_the_reply_goes_to_the_chat(self):
        adapter = _outbound()

        await adapter.deliver(AgentReplyText(response="agent says hi"), {"chat_id": str(CHAT_ID)})

        assert adapter._client.send_message.await_args.args == (str(CHAT_ID), ["agent says hi"])

    @pytest.mark.asyncio
    async def test_a_long_reply_is_split_at_the_telegram_limit(self):
        adapter = _outbound()

        await adapter.deliver(AgentReplyText(response="x" * 5000), {"chat_id": str(CHAT_ID)})

        assert [len(c) for c in adapter._client.send_message.await_args.args[1]] == [4096, 904]

    @pytest.mark.asyncio
    async def test_the_acknowledgement_is_a_typing_indicator(self):
        adapter = _outbound()

        assert await adapter.acknowledge({"chat_id": str(CHAT_ID)}) == {}

        assert adapter._client.chat_action.await_args.args == (str(CHAT_ID), "typing")

    @pytest.mark.asyncio
    async def test_an_error_reaches_the_user(self):
        adapter = _outbound()
        await adapter.deliver_error("Sorry, something broke.", {"chat_id": str(CHAT_ID)})
        assert adapter._client.send_message.await_args.args == (str(CHAT_ID), ["Sorry, something broke."])


class TestRoute:
    def _client(self, transport):
        handler = WebhookRESTRequestHandler(_inbound(), producer=IntegrationProducer(transport))
        app = FastAPI()
        app.include_router(handler.get_router())
        return TestClient(app)

    def test_a_verified_update_is_enqueued_and_acknowledged(self):
        transport = InMemoryTransport()

        response = self._client(transport).post("/telegram/webhook", json=_update(), headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})

        # The route answers immediately; the agent runs on the far side of the queue.
        assert response.status_code == 200 and response.json() == {"ok": True}
        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)
        assert message.attributes["integration"] == "telegram"
        assert message.attributes["reply_chat_id"] == str(CHAT_ID)

    def test_an_update_without_the_secret_is_rejected(self):
        transport = InMemoryTransport()
        assert self._client(transport).post("/telegram/webhook", json=_update()).status_code == 403
        assert transport.create_consumer(QueueName.INPUT).fetch(1, 0.05) == []
