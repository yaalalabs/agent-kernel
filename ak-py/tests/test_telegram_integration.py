"""Telegram adapter: update -> InboundRequest, and agent reply -> Bot API sends."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentkernel.core.config import AKConfig
from agentkernel.core.event import PausedInterruption
from agentkernel.core.model import AgentPausedReplyAny, AgentReplyText, AgentRequestText, AgentResumeRequestAny
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.integration.telegram.adapter import (
    CALLBACK_LIMIT,
    CALLBACK_PREFIX,
    HELP_MESSAGE,
    START_MESSAGE,
    TelegramInboundAdapter,
    TelegramOutboundAdapter,
    _TelegramClient,
)
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


def _paused(*interruption_ids, kind="tool_call"):
    return AgentPausedReplyAny(
        run_id="01JD7K2MX4",
        session_id=str(CHAT_ID),
        agent="helper",
        interruptions=[PausedInterruption(id=i, kind=kind, tool_name="refund_order", arguments='{"order_id": "A-10294"}') for i in interruption_ids],
    )


def _press(data, update_id=101, message_id=812):
    return {
        "update_id": update_id,
        "callback_query": {"id": "cb-1", "data": data, "from": {"id": 99}, "message": {"message_id": message_id, "chat": {"id": CHAT_ID}}},
    }


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
    async def test_a_press_on_a_pause_button_becomes_a_decision(self):
        adapter = _inbound()

        [request] = (await adapter.parse(_fake_request(_press(f"{CALLBACK_PREFIX}a:call_9f2b")))).requests

        [resume] = request.requests
        assert isinstance(resume, AgentResumeRequestAny)
        assert resume.run_id is None, "the runtime resolves the run from the interruption id"
        assert [(d.id, d.status) for d in resume.decisions] == [("call_9f2b", "approved")]
        assert request.prompt == ""
        assert request.user_id == "99", "who pressed is what lets a pre-hook decide whether they may"
        adapter._client.answer_callback_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_press_is_identified_by_the_decision_not_the_update(self):
        """update_id is minted per press, so a second click on one button must not be a new request."""
        first = (await _inbound().parse(_fake_request(_press(f"{CALLBACK_PREFIX}a:call_9f2b", update_id=101)))).requests[0]
        again = (await _inbound().parse(_fake_request(_press(f"{CALLBACK_PREFIX}a:call_9f2b", update_id=102)))).requests[0]
        other_verb = (await _inbound().parse(_fake_request(_press(f"{CALLBACK_PREFIX}d:call_9f2b", update_id=103)))).requests[0]

        assert first.request_id == again.request_id == f"telegram:{CHAT_ID}:812:call_9f2b:approved"
        assert other_verb.request_id != first.request_id, "approve then deny are two decisions, not a repeat"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [f"{CALLBACK_PREFIX}z:call_9f2b", f"{CALLBACK_PREFIX}a:", CALLBACK_PREFIX])
    async def test_a_press_that_does_not_parse_is_ignored(self, data):
        assert (await _inbound().parse(_fake_request(_press(data)))).requests == []

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


class TestPauseRendering:
    """A paused run drawn as one message per question, each with the keyboard that answers it."""

    @staticmethod
    def _messages(adapter):
        return [("".join(call.args[1]), call.kwargs.get("reply_markup")) for call in adapter._client.send_message.await_args_list]

    @pytest.mark.asyncio
    async def test_one_question_is_still_one_message(self):
        adapter = _outbound()

        await adapter.deliver_paused(_paused("call_9f2b"), {"chat_id": str(CHAT_ID)})

        [(text, markup)] = self._messages(adapter)
        assert "Approval needed" in text and "refund_order" in text and "paused until someone approves" in text
        assert markup == {
            "inline_keyboard": [
                [
                    {"text": "✓ Approve", "callback_data": f"{CALLBACK_PREFIX}a:call_9f2b"},
                    {"text": "✗ Deny", "callback_data": f"{CALLBACK_PREFIX}d:call_9f2b"},
                ]
            ]
        }

    @pytest.mark.asyncio
    async def test_each_question_gets_its_own_message_and_keyboard(self):
        adapter = _outbound()

        await adapter.deliver_paused(_paused("call_a", "call_b"), {"chat_id": str(CHAT_ID)})

        messages = self._messages(adapter)
        assert len(messages) == 2, "a keyboard renders at the foot of its message, so each question needs one"
        assert [markup["inline_keyboard"][0][0]["callback_data"] for _, markup in messages] == [
            f"{CALLBACK_PREFIX}a:call_a",
            f"{CALLBACK_PREFIX}a:call_b",
        ]
        assert all(button["text"] in ("✓ Approve", "✗ Deny") for _, markup in messages for button in markup["inline_keyboard"][0])

    @pytest.mark.asyncio
    async def test_the_opening_and_closing_lines_ride_the_first_and_last_question(self):
        adapter = _outbound()

        await adapter.deliver_paused(_paused("call_a", "call_b"), {"chat_id": str(CHAT_ID)})

        first, last = self._messages(adapter)
        assert first[0].startswith("⏸ Approval needed"), "the opening line takes no message of its own"
        assert last[0].rstrip().endswith("This run is paused until someone approves it.")
        assert "Approval needed" not in last[0]

    @pytest.mark.asyncio
    async def test_the_keyboard_rides_the_last_chunk_only(self):
        adapter = _outbound()
        adapter.MESSAGE_LIMIT = 40

        await adapter.deliver_paused(_paused("call_9f2b"), {"chat_id": str(CHAT_ID)})

        chunks = adapter._client.send_message.await_args.args[1]
        assert len(chunks) > 1, "this question is longer than the limit, so it is split"
        assert adapter._client.send_message.await_args.kwargs["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_a_question_wanting_a_value_gets_a_note_instead_of_a_keyboard(self):
        adapter = _outbound()

        await adapter.deliver_paused(_paused("call_q", kind="input_required"), {"chat_id": str(CHAT_ID)})

        [(text, markup)] = self._messages(adapter)
        assert markup is None, "Approve answers nothing when the agent asked for a value"
        assert adapter.TYPED_ANSWER_NOTICE in text, "the note sits in the message the question is in"

    @pytest.mark.asyncio
    async def test_an_over_budget_id_loses_its_keyboard_while_its_siblings_keep_theirs(self, caplog):
        adapter = _outbound()
        too_long = "x" * CALLBACK_LIMIT

        with caplog.at_level(logging.WARNING, logger="ak.integration.telegram"):
            await adapter.deliver_paused(_paused("call_a", too_long), {"chat_id": str(CHAT_ID)})

        first, last = self._messages(adapter)
        assert first[1] is not None
        assert last[1] is None and adapter.UNPRESSABLE_NOTICE in last[0]
        assert "callback_data" in caplog.text, "the reason belongs in the log, not in front of the user"

    @pytest.mark.asyncio
    async def test_a_cancelled_verb_is_offered_when_the_adapter_declares_it(self):
        adapter = _outbound()
        adapter.DECISIONS = ("approved", "denied", "cancelled")

        await adapter.deliver_paused(_paused("call_a"), {"chat_id": str(CHAT_ID)})

        [row] = adapter._client.send_message.await_args.kwargs["reply_markup"]["inline_keyboard"]
        assert [button["text"] for button in row] == ["✓ Approve", "✗ Deny", "⊘ Cancel"]
