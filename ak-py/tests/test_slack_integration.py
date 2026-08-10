import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("slack_bolt")

from agentkernel.core.model import (  # noqa: E402
    AgentReplyAny,
    AgentReplyText,
    AgentRequestAny,
    AgentRequestImage,
    AgentRequestText,
)
from agentkernel.integration.slack.slack_chat import AgentSlackRequestHandler  # noqa: E402

BOT_ID = "B_BOT"


class FakeSay:
    """Records say() calls; carries the client used for acknowledgement updates."""

    def __init__(self):
        self.calls = []
        self.client = MagicMock()
        self.client.chat_update = AsyncMock()

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"ts": "ack-ts", "channel": kwargs.get("channel")}


class FakeChatService:
    """Stands in for the ChatService core: records execute() calls."""

    def __init__(self, reply=None, error=None):
        self.reply = reply if reply is not None else AgentReplyText(response="agent says hi")
        self.error = error
        self.calls = []

    async def execute(self, req, requests=None):
        self.calls.append((req, requests))
        if self.error:
            raise self.error
        return self.reply, req.session_id


def _handler(chat_service, agent="helper", ack=None):
    """Build the handler without running __init__ (no Slack app, no config)."""
    handler = object.__new__(AgentSlackRequestHandler)
    handler._log = logging.getLogger("ak.api.slack.test")
    handler._slack_agent = agent
    handler._slack_agent_acknowledgement = ack
    handler._max_file_size = 10 * 1024 * 1024
    handler._bot_id = BOT_ID
    handler._slack_app = MagicMock()
    handler._chat_service = chat_service
    return handler


def _body(text=f"hello <@{BOT_ID}>", user="U123", channel="C9", ts="111.222", thread_ts=None, files=None):
    body = {"user": user, "text": text, "channel": channel, "ts": ts}
    if thread_ts:
        body["thread_ts"] = thread_ts
    if files:
        body["files"] = files
    return body


@pytest.mark.asyncio
async def test_message_routes_through_chat_service_core():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    say = FakeSay()

    await handler.handle(_body(thread_ts="000.111"), say)

    assert len(chat_service.calls) == 1
    req, requests = chat_service.calls[0]
    assert req.prompt == "hello"
    assert req.agent == "helper"
    assert req.session_id == "000.111"  # thread_ts wins over ts
    assert req.user_id == "U123"
    assert req.group_id == "C9"
    assert isinstance(requests[0], AgentRequestText) and requests[0].prompt == "hello"
    assert isinstance(requests[-1], AgentRequestAny) and requests[-1].name == "body"
    assert requests[-1].content["channel"] == "C9"

    final = say.calls[-1]
    assert final["blocks"][0]["text"]["text"] == "agent says hi"
    assert final["thread_ts"] == "000.111"


@pytest.mark.asyncio
async def test_attachment_only_message_calls_execute_with_empty_prompt():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    async def fake_download(url):
        return b"imgbytes"

    handler._download_slack_file = fake_download
    files = [{"name": "pic.png", "mimetype": "image/png", "size": 10, "url_private": "https://files.slack/x"}]

    await handler.handle(_body(text=f"<@{BOT_ID}>", files=files), FakeSay())

    req, requests = chat_service.calls[0]
    assert req.prompt == ""
    assert isinstance(requests[0], AgentRequestImage) and requests[0].name == "pic.png"
    assert isinstance(requests[-1], AgentRequestAny)


@pytest.mark.asyncio
async def test_value_error_maps_to_no_agent_message():
    chat_service = FakeChatService(error=ValueError("No agent available"))
    handler = _handler(chat_service)
    say = FakeSay()

    await handler.handle(_body(), say)

    assert say.calls[-1]["text"] == "No agent available to handle your request."


@pytest.mark.asyncio
async def test_generic_error_maps_to_error_message():
    chat_service = FakeChatService(error=RuntimeError("agent blew up"))
    handler = _handler(chat_service)
    say = FakeSay()

    await handler.handle(_body(), say)

    assert say.calls[-1]["text"] == "Error handling your request."


@pytest.mark.asyncio
async def test_ignores_own_bot_messages():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    say = FakeSay()

    await handler.handle(_body(user=BOT_ID), say)

    assert chat_service.calls == []
    assert say.calls == []


@pytest.mark.asyncio
async def test_empty_message_prompts_for_content():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    say = FakeSay()

    await handler.handle(_body(text=f"<@{BOT_ID}>"), say)

    assert chat_service.calls == []
    assert say.calls[-1]["text"] == "Please provide a message or attachment."


@pytest.mark.asyncio
async def test_audio_video_files_rejected_before_execute():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    say = FakeSay()
    files = [{"name": "song.mp3", "mimetype": "audio/mpeg", "size": 10}]

    await handler.handle(_body(files=files), say)

    assert chat_service.calls == []
    assert "audio/video files were rejected" in say.calls[-1]["text"]


@pytest.mark.asyncio
async def test_acknowledgement_flow_updates_placeholder():
    chat_service = FakeChatService()
    handler = _handler(chat_service, ack="working on it")
    say = FakeSay()

    await handler.handle(_body(), say)

    assert ":rolling-loader:" in say.calls[0]["text"]
    say.client.chat_update.assert_awaited_once()
    assert say.calls[-1]["thread_ts"] == "ack-ts"  # reply threads under the ack message


@pytest.mark.asyncio
async def test_structured_reply_formats_as_json():
    chat_service = FakeChatService(reply=AgentReplyAny(content={"a": 1}))
    handler = _handler(chat_service)
    say = FakeSay()

    await handler.handle(_body(), say)

    assert say.calls[-1]["blocks"][0]["text"]["text"] == '{"a": 1}'


def test_split_reply_chunks_and_truncates():
    handler = _handler(FakeChatService())

    assert len(handler._split_reply("x" * 3000)) == 1
    assert len(handler._split_reply("x" * 3001)) == 2

    blocks = handler._split_reply("x" * (3000 * 6))
    assert len(blocks) == 6
    assert "truncated" in blocks[-1]["text"]["text"]
