import logging

import pytest

from agentkernel.core.model import AgentReplyText, AgentRequestImage, AgentRequestText
from agentkernel.integration.whatsapp.whatsapp_chat import AgentWhatsAppRequestHandler

FROM_NUMBER = "15551234"


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


def _handler(chat_service, agent="helper"):
    """Build the handler without running __init__ (no config, no HTTP client)."""
    handler = object.__new__(AgentWhatsAppRequestHandler)
    handler._log = logging.getLogger("ak.api.whatsapp.test")
    handler._whatsapp_agent = agent
    handler._whatsapp_agent_acknowledgement = None
    handler._max_file_size = 10 * 1024 * 1024
    handler._chat_service = chat_service
    handler.sent = []

    async def fake_send(to_number, text, reply_to_message_id=None):
        handler.sent.append((to_number, text, reply_to_message_id))

    handler._send_message = fake_send
    return handler


def _text_message(body="hello"):
    return {"id": "m1", "from": FROM_NUMBER, "type": "text", "text": {"body": body}}


@pytest.mark.asyncio
async def test_text_message_routes_through_chat_service_core():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    await handler._handle_message(_text_message(), {})

    assert len(chat_service.calls) == 1
    req, requests = chat_service.calls[0]
    assert req.prompt == "hello"
    assert req.agent == "helper"
    assert req.session_id == FROM_NUMBER
    assert req.user_id == FROM_NUMBER
    assert isinstance(requests[0], AgentRequestText) and requests[0].prompt == "hello"

    assert handler.sent[-1] == (FROM_NUMBER, "agent says hi", "m1")


@pytest.mark.asyncio
async def test_image_message_builds_multimodal_requests():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    async def fake_media_info(media_id):
        return 100, "image/png"

    async def fake_download(media_id):
        return "aW1n"

    handler._get_media_info = fake_media_info
    handler._download_media = fake_download

    message = {"id": "m2", "from": FROM_NUMBER, "type": "image", "image": {"id": "media-1", "caption": ""}}
    await handler._handle_message(message, {})

    req, requests = chat_service.calls[0]
    assert req.prompt == "[Image received]"
    assert isinstance(requests[0], AgentRequestText)
    assert isinstance(requests[1], AgentRequestImage) and requests[1].mime_type == "image/png"


@pytest.mark.asyncio
async def test_value_error_maps_to_no_agent_message():
    chat_service = FakeChatService(error=ValueError("No agent available"))
    handler = _handler(chat_service)

    await handler._handle_message(_text_message(), {})

    assert handler.sent[-1][1] == "Sorry, no agent is available to handle your request."


@pytest.mark.asyncio
async def test_generic_error_maps_to_error_message():
    chat_service = FakeChatService(error=RuntimeError("agent blew up"))
    handler = _handler(chat_service)

    await handler._handle_message(_text_message(), {})

    assert handler.sent[-1][1] == "Sorry, there was an error processing your request."


@pytest.mark.asyncio
async def test_audio_video_rejected_before_execute():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    await handler._handle_message({"id": "m3", "from": FROM_NUMBER, "type": "audio"}, {})

    assert chat_service.calls == []
    assert handler.sent[-1][1] == "Sorry, audio and video messages are not supported yet."


@pytest.mark.asyncio
async def test_oversized_media_rejected_before_execute():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    async def fake_media_info(media_id):
        return handler._max_file_size + 1, "image/png"

    handler._get_media_info = fake_media_info

    message = {"id": "m4", "from": FROM_NUMBER, "type": "image", "image": {"id": "media-1"}}
    await handler._handle_message(message, {})

    assert chat_service.calls == []
    assert "exceeds the maximum allowed size" in handler.sent[-1][1]
