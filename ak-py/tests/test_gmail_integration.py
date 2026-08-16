import logging

import pytest

pytest.importorskip("googleapiclient")

from agentkernel.core.model import AgentReplyText, AgentRequestImage, AgentRequestText  # noqa: E402
from agentkernel.integration.gmail.gmail_chat import AgentGmailRequestHandler  # noqa: E402

SENDER = "alice@example.com"


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
    """Build the handler without running __init__ (no OAuth, no Gmail client)."""
    handler = object.__new__(AgentGmailRequestHandler)
    handler._log = logging.getLogger("ak.api.gmail.test")
    handler._gmail_agent = agent
    handler._chat_service = chat_service
    return handler


@pytest.mark.asyncio
async def test_text_email_routes_through_chat_service_core():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    response = await handler._process_with_agent(SENDER, "Greetings", "Hello agent", session_id="thread-1")

    assert response == "agent says hi"
    assert len(chat_service.calls) == 1
    req, requests = chat_service.calls[0]
    assert req.prompt == f"From: {SENDER}\nSubject: Greetings\n\nHello agent"
    assert req.agent == "helper"
    assert req.session_id == "thread-1"
    assert req.user_id == SENDER
    assert len(requests) == 1
    assert isinstance(requests[0], AgentRequestText) and requests[0].prompt == req.prompt


@pytest.mark.asyncio
async def test_session_id_falls_back_to_sender():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    await handler._process_with_agent(SENDER, "Subj", "Body", session_id=None)

    req, _ = chat_service.calls[0]
    assert req.session_id == SENDER


@pytest.mark.asyncio
async def test_thread_history_included_in_prompt():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    await handler._process_with_agent(SENDER, "Subj", "Body", session_id="t1", thread_history="earlier mail")

    req, _ = chat_service.calls[0]
    assert req.prompt.startswith("Thread history:\nearlier mail")
    assert "New message:" in req.prompt


@pytest.mark.asyncio
async def test_attachments_ride_in_the_same_execute_call():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    image = AgentRequestImage(image_data="aW1n", name="scan.png", mime_type="image/png")

    await handler._process_with_agent(SENDER, "Subj", "Body", session_id="t1", attachments=[image])

    assert len(chat_service.calls) == 1  # single collapsed path, no run/run_multi split
    _, requests = chat_service.calls[0]
    assert isinstance(requests[0], AgentRequestText)
    assert requests[1] is image


@pytest.mark.asyncio
async def test_value_error_returns_none():
    chat_service = FakeChatService(error=ValueError("No agent available"))
    handler = _handler(chat_service)

    response = await handler._process_with_agent(SENDER, "Subj", "Body", session_id="t1")

    assert response is None


@pytest.mark.asyncio
async def test_generic_error_returns_none():
    chat_service = FakeChatService(error=RuntimeError("agent blew up"))
    handler = _handler(chat_service)

    response = await handler._process_with_agent(SENDER, "Subj", "Body", session_id="t1")

    assert response is None
