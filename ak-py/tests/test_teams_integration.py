import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytest.importorskip("botbuilder.core")

from botbuilder.schema import Activity, ActivityTypes  # noqa: E402

from agentkernel.core.config import AKConfig  # noqa: E402
from agentkernel.core.model import (  # noqa: E402
    AgentReplyAny,
    AgentReplyText,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)
from agentkernel.integration.teams.teams_chat import (  # noqa: E402
    FILE_DOWNLOAD_INFO,
    MAX_MESSAGE_LENGTH,
    AgentTeamsRequestHandler,
    _AttachmentTooLarge,
)

BOT_ID = "28:bot-app-id"
BOT_NAME = "AgentBot"


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


class FakeTurnContext:
    """Records the activities the handler sends back to Teams."""

    def __init__(self, activity=None):
        self.activity = activity
        self.sent = []

    async def send_activity(self, activity):
        self.sent.append(activity)
        return {"id": "sent"}

    @property
    def texts(self):
        return [a for a in self.sent if isinstance(a, str)]


def _handler(chat_service=None, agent="helper", ack=None, tenant_id=""):
    """Build the handler without running __init__ (no adapter, no config, no network)."""
    handler = object.__new__(AgentTeamsRequestHandler)
    handler._log = logging.getLogger("ak.api.teams.test")
    handler._teams_agent = agent
    handler._teams_agent_acknowledgement = ack
    handler._app_id = "app-id"
    handler._app_password = "app-password"
    handler._tenant_id = tenant_id
    handler._max_file_size = 10 * 1024 * 1024
    handler._chat_service = chat_service if chat_service is not None else FakeChatService()
    handler._adapter = MagicMock()
    handler._adapter.continue_conversation = AsyncMock()
    handler._msal_apps = {}
    handler._bot_credentials = None
    handler._background_tasks = set()
    return handler


def _activity(text=f"<at>{BOT_NAME}</at> hello", attachments=None, entities=None, activity_type=ActivityTypes.message, channel_data=None):
    payload = {
        "type": activity_type,
        "id": "act-1",
        "text": text,
        "from": {"id": "user-1", "name": "Alice"},
        "conversation": {"id": "conv-1", "conversationType": "personal", "tenantID": "tenant-from-activity"},
        "recipient": {"id": BOT_ID, "name": BOT_NAME},
        "channelId": "msteams",
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
    }
    if attachments is not None:
        payload["attachments"] = attachments
    if entities is not None:
        payload["entities"] = entities
    if channel_data is not None:
        payload["channelData"] = channel_data
    return Activity().deserialize(payload)


async def _handle(handler, activity, text=None, attachments=None):
    """Drive the post-webhook half of the turn the way _run_agent_turn does."""
    turn_context = FakeTurnContext(activity)
    resolved_text = handler._strip_mentions(activity) if text is None else text
    resolved_attachments = [a for a in (activity.attachments or []) if (a.content_type or "") != "text/html"] if attachments is None else attachments
    await handler._handle_teams_message(turn_context, activity, resolved_text, resolved_attachments, "Alice")
    return turn_context


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


def test_akconfig_exposes_a_teams_block():
    """Regression for #619: the handler reads Config.get().teams, which never existed."""
    config = AKConfig()
    assert config.teams.agent == ""
    assert config.teams.agent_acknowledgement == ""
    assert config.teams.app_id == ""
    assert config.teams.app_password == ""
    assert config.teams.tenant_id == ""


def test_teams_env_vars_bind_to_the_config(monkeypatch):
    monkeypatch.setenv("AK_TEAMS__APP_ID", "env-app-id")
    monkeypatch.setenv("AK_TEAMS__APP_PASSWORD", "env-secret")
    monkeypatch.setenv("AK_TEAMS__AGENT", "env-agent")

    config = AKConfig()

    assert config.teams.app_id == "env-app-id"
    assert config.teams.app_password == "env-secret"
    assert config.teams.agent == "env-agent"


# --------------------------------------------------------------------------------------
# Message flow
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_routes_through_chat_service_core():
    chat_service = FakeChatService()
    handler = _handler(chat_service)

    turn_context = await _handle(handler, _activity(channel_data={"channel": {"id": "19:channel-1"}}))

    assert len(chat_service.calls) == 1
    req, requests = chat_service.calls[0]
    assert req.prompt == "hello"
    assert req.agent == "helper"
    assert req.session_id == "conv-1"
    assert req.user_id == "user-1"
    assert req.group_id == "19:channel-1"
    assert isinstance(requests[0], AgentRequestText) and requests[0].prompt == "hello"
    assert turn_context.texts == ["agent says hi"]


@pytest.mark.asyncio
async def test_non_message_activity_is_ignored():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    turn_context = FakeTurnContext(_activity(activity_type=ActivityTypes.conversation_update))

    await handler._on_turn(turn_context)

    assert chat_service.calls == []
    assert turn_context.sent == []
    handler._adapter.continue_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_run_is_offloaded_from_the_webhook_turn():
    """The webhook must return before the agent runs, or Azure redelivers the activity."""
    handler = _handler()
    turn_context = FakeTurnContext(_activity())

    await handler._on_turn(turn_context)
    await asyncio.gather(*list(handler._background_tasks))

    handler._adapter.continue_conversation.assert_awaited_once()
    reference, callback, bot_id = handler._adapter.continue_conversation.await_args.args
    assert reference.conversation.id == "conv-1"
    assert bot_id == "app-id"
    assert callable(callback)


@pytest.mark.asyncio
async def test_acknowledgement_is_sent_on_the_webhook_turn():
    handler = _handler(ack="I'm looking into that for you...")
    turn_context = FakeTurnContext(_activity())

    await handler._on_turn(turn_context)
    await asyncio.gather(*list(handler._background_tasks))

    assert turn_context.texts == ["Hi Alice, I'm looking into that for you..."]


@pytest.mark.asyncio
async def test_empty_activity_is_dropped_without_a_reply():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    turn_context = FakeTurnContext(_activity(text=f"<at>{BOT_NAME}</at>"))

    await handler._on_turn(turn_context)

    assert chat_service.calls == []
    assert turn_context.sent == []


@pytest.mark.asyncio
async def test_message_with_no_usable_content_prompts_for_content():
    """An @mention-only post whose only attachment is the html body rendition."""
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    activity = _activity(text=f"<at>{BOT_NAME}</at>", attachments=[{"contentType": "text/html", "content": "<div>hi</div>"}])

    turn_context = await _handle(handler, activity)

    assert chat_service.calls == []
    assert turn_context.texts == ["Please provide a message or attachment."]


@pytest.mark.asyncio
async def test_value_error_maps_to_no_agent_message():
    handler = _handler(FakeChatService(error=ValueError("No agent available")))

    turn_context = await _handle(handler, _activity())

    assert turn_context.texts == ["No agent available to handle your request."]


@pytest.mark.asyncio
async def test_generic_error_maps_to_error_message():
    handler = _handler(FakeChatService(error=RuntimeError("agent blew up")))

    turn_context = await _handle(handler, _activity())

    assert turn_context.texts == ["Sorry Alice, an error occurred while processing your request."]


@pytest.mark.asyncio
async def test_structured_reply_formats_as_json():
    handler = _handler(FakeChatService(reply=AgentReplyAny(content={"a": 1})))

    turn_context = await _handle(handler, _activity())

    assert turn_context.texts == ['{"a": 1}']


@pytest.mark.asyncio
async def test_long_reply_is_chunked_instead_of_dropped():
    handler = _handler(FakeChatService(reply=AgentReplyText(response="x" * (MAX_MESSAGE_LENGTH * 2 + 5))))

    turn_context = await _handle(handler, _activity())

    assert len(turn_context.texts) == 3
    assert all(len(chunk) <= MAX_MESSAGE_LENGTH for chunk in turn_context.texts)


def test_split_reply_chunks_on_the_teams_limit():
    handler = _handler()

    assert len(handler._split_reply("x" * MAX_MESSAGE_LENGTH)) == 1
    assert len(handler._split_reply("x" * (MAX_MESSAGE_LENGTH + 1))) == 2


# --------------------------------------------------------------------------------------
# Mention handling
# --------------------------------------------------------------------------------------


def test_strip_mentions_removes_only_the_bot_mention():
    handler = _handler()
    activity = _activity(
        text=f'<at id="0">{BOT_NAME}</at> please tell <at id="1">Bob</at> it is done',
        entities=[
            {"type": "mention", "text": f'<at id="0">{BOT_NAME}</at>', "mentioned": {"id": BOT_ID, "name": BOT_NAME}},
            {"type": "mention", "text": '<at id="1">Bob</at>', "mentioned": {"id": "29:bob", "name": "Bob"}},
        ],
    )

    assert handler._strip_mentions(activity) == "please tell Bob it is done"


def test_strip_mentions_preserves_emails_and_handles():
    handler = _handler()
    activity = _activity(text=f"<at>{BOT_NAME}</at> email billing@contoso.com and explain @staticmethod")

    assert handler._strip_mentions(activity) == "email billing@contoso.com and explain @staticmethod"


def test_strip_mentions_preserves_newlines():
    handler = _handler()
    activity = _activity(text=f"<at>{BOT_NAME}</at> review this:\n\n    def f():\n        pass")

    assert handler._strip_mentions(activity) == "review this:\n\n    def f():\n        pass"


def test_strip_mentions_handles_the_id_carrying_tag_without_entities():
    handler = _handler()
    activity = _activity(text=f'<at id="0">{BOT_NAME}</at> hello', entities=[])

    assert handler._strip_mentions(activity) == "hello"


# --------------------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------------------


def _file_attachment(name="report.pdf", url="https://contoso.sharepoint.com/x?tempauth=jwt", file_type="pdf"):
    return {
        "contentType": FILE_DOWNLOAD_INFO,
        "name": name,
        "content": {"downloadUrl": url, "fileType": file_type, "uniqueId": "u1"},
    }


@pytest.mark.asyncio
async def test_uploaded_file_is_added_to_the_request():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    handler._download = AsyncMock(return_value=(b"%PDF-1.4", "application/pdf"))

    await _handle(handler, _activity(attachments=[_file_attachment()]))

    _, requests = chat_service.calls[0]
    assert isinstance(requests[1], AgentRequestFile)
    assert requests[1].name == "report.pdf"
    assert requests[1].mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_inline_image_is_authorized_with_a_bot_framework_token():
    """Inline images live on the Bot Connector and 401 without the bot's own token."""
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    handler._bot_framework_token = AsyncMock(return_value="bf-token")
    captured = {}

    async def fake_download(url, headers):
        captured["url"] = url
        captured["headers"] = headers
        return b"\x89PNG", "image/png"

    handler._download = fake_download
    activity = _activity(
        text=f"<at>{BOT_NAME}</at> what is this",
        attachments=[{"contentType": "image/*", "contentUrl": "https://smba.trafficmanager.net/emea/v3/attachments/1/views/original"}],
    )

    await _handle(handler, activity)

    assert captured["headers"] == {"Authorization": "Bearer bf-token"}
    _, requests = chat_service.calls[0]
    assert isinstance(requests[1], AgentRequestImage)
    assert requests[1].mime_type == "image/png"
    assert requests[1].name == "image.png"


@pytest.mark.asyncio
async def test_audio_and_video_are_rejected_before_any_download():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    handler._download = AsyncMock(side_effect=AssertionError("must not download rejected media"))

    turn_context = FakeTurnContext(_activity(attachments=[_file_attachment(name="demo.mp4", file_type="mp4")]))
    await handler._on_turn(turn_context)

    assert chat_service.calls == []
    handler._adapter.continue_conversation.assert_not_awaited()
    assert "audio/video files were rejected" in turn_context.texts[-1]
    assert "demo.mp4" in turn_context.texts[-1]


@pytest.mark.asyncio
async def test_oversized_file_gets_its_own_message():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    handler._download = AsyncMock(side_effect=_AttachmentTooLarge(50 * 1024 * 1024))

    turn_context = await _handle(handler, _activity(attachments=[_file_attachment(name="big.zip", file_type="zip")]))

    assert chat_service.calls == []
    assert "exceed the maximum size" in turn_context.texts[-1]
    assert "big.zip (50.00 MB)" in turn_context.texts[-1]


@pytest.mark.asyncio
async def test_download_failure_is_reported_as_a_download_failure():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    handler._download = AsyncMock(return_value=(None, None))

    turn_context = await _handle(handler, _activity(attachments=[_file_attachment()]))

    assert chat_service.calls == []
    assert turn_context.texts[-1] == "Sorry Alice, I could not download the following files: report.pdf. Please try again."


@pytest.mark.asyncio
async def test_authorization_failure_is_reported_separately_from_a_download_failure():
    chat_service = FakeChatService()
    handler = _handler(chat_service)
    handler._download = AsyncMock(side_effect=AssertionError("must not download without authorization"))
    activity = _activity(attachments=[_file_attachment(url="https://contoso.sharepoint.com/download.aspx?UniqueId=1")])
    activity.conversation.tenant_id = None

    turn_context = await _handle(handler, activity)

    assert chat_service.calls == []
    assert "not allowed to download" in turn_context.texts[-1]
    assert "contact your administrator" in turn_context.texts[-1]


# --------------------------------------------------------------------------------------
# Download authorization
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_authenticated_url_gets_no_authorization_header():
    handler = _handler()

    headers = await handler._download_headers("https://contoso.sharepoint.com/x?tempauth=jwt", "tenant-1")

    assert headers == {}


@pytest.mark.asyncio
async def test_unknown_host_is_never_handed_a_bearer_token():
    handler = _handler()
    handler._acquire_token = MagicMock(side_effect=AssertionError("must not mint a token for an unknown host"))

    headers = await handler._download_headers("https://evil.example.com/steal", "tenant-1")

    assert headers == {}


@pytest.mark.asyncio
async def test_sharepoint_download_uses_a_tenant_scoped_app_only_token():
    handler = _handler()
    handler._acquire_token = MagicMock(return_value={"access_token": "spo-token"})

    headers = await handler._download_headers("https://contoso.sharepoint.com/download.aspx?UniqueId=1", "tenant-1")

    assert headers == {"Authorization": "Bearer spo-token"}
    handler._acquire_token.assert_called_once_with("tenant-1", "https://contoso.sharepoint.com/.default")


@pytest.mark.asyncio
async def test_app_only_token_is_refused_without_a_tenant():
    """The client credentials grant is not valid against the /common authority."""
    handler = _handler()

    with pytest.raises(PermissionError, match="teams.tenant_id"):
        await handler._download_headers("https://contoso.sharepoint.com/download.aspx?UniqueId=1", None)


@pytest.mark.asyncio
async def test_token_acquisition_failure_raises_instead_of_falling_through():
    handler = _handler()
    handler._acquire_token = MagicMock(return_value={"error": "invalid_client", "error_description": "AADSTS7000215"})

    with pytest.raises(PermissionError, match="AADSTS7000215"):
        await handler._download_headers("https://contoso.sharepoint.com/download.aspx?UniqueId=1", "tenant-1")


def test_resolve_tenant_prefers_the_activity_over_the_configuration():
    """A client credentials grant needs the customer's tenant, not the bot's home tenant."""
    handler = _handler(tenant_id="configured-tenant")

    assert handler._resolve_tenant(_activity()) == "tenant-from-activity"

    # Teams itself sends the tenant in channelData; the adapter copies it onto the
    # conversation, so the raw channelData is the fallback.
    activity = _activity(channel_data={"tenant": {"id": "channel-data-tenant"}})
    activity.conversation.tenant_id = None
    assert handler._resolve_tenant(activity) == "channel-data-tenant"

    activity.channel_data = None
    assert handler._resolve_tenant(activity) == "configured-tenant"

    assert _handler(tenant_id="")._resolve_tenant(activity) is None


# --------------------------------------------------------------------------------------
# Streaming download
# --------------------------------------------------------------------------------------


def _mock_httpx(monkeypatch, responder):
    transport = httpx.MockTransport(responder)
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_download_returns_content_and_type(monkeypatch):
    handler = _handler()
    _mock_httpx(monkeypatch, lambda request: httpx.Response(200, content=b"hello", headers={"content-type": "application/pdf; charset=utf-8"}))

    data, content_type = await handler._download("https://host/file", {})

    assert data == b"hello"
    assert content_type == "application/pdf"


@pytest.mark.asyncio
async def test_download_reports_a_non_200_as_a_failure(monkeypatch):
    handler = _handler()
    _mock_httpx(monkeypatch, lambda request: httpx.Response(401, content=b"denied"))

    assert await handler._download("https://host/file", {}) == (None, None)


@pytest.mark.asyncio
async def test_download_rejects_an_oversized_body_from_content_length(monkeypatch):
    handler = _handler()
    handler._max_file_size = 8
    _mock_httpx(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 64))

    with pytest.raises(_AttachmentTooLarge):
        await handler._download("https://host/file", {})


@pytest.mark.asyncio
async def test_download_aborts_a_chunked_body_that_grows_past_the_limit(monkeypatch):
    """Without a content-length the cap has to be enforced while streaming."""
    handler = _handler()
    handler._max_file_size = 8

    def responder(request):
        async def chunks():
            for _ in range(10):
                yield b"xxxx"

        return httpx.Response(200, content=chunks())

    _mock_httpx(monkeypatch, responder)

    with pytest.raises(_AttachmentTooLarge):
        await handler._download("https://host/file", {})


# --------------------------------------------------------------------------------------
# Webhook route
# --------------------------------------------------------------------------------------


def _client(handler):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(handler.get_router())
    return TestClient(app, raise_server_exceptions=False)


def test_health_route():
    assert _client(_handler()).get("/health").json() == {"status": "ok"}


def test_failed_bot_framework_auth_returns_401_not_500():
    """Azure retries 5xx, so a rejected JWT must not be reported as a server error."""
    handler = _handler()
    handler._adapter.process_activity = AsyncMock(side_effect=PermissionError("Unauthorized Access."))

    response = _client(handler).post("/teams/messages", json={"type": "message"})

    assert response.status_code == 401


def test_unexpected_failure_still_returns_500():
    handler = _handler()
    handler._adapter.process_activity = AsyncMock(side_effect=RuntimeError("boom"))

    response = _client(handler).post("/teams/messages", json={"type": "message"})

    assert response.status_code == 500


def test_invoke_activities_get_their_invoke_response_body():
    from botbuilder.schema import InvokeResponse

    handler = _handler()
    handler._adapter.process_activity = AsyncMock(return_value=InvokeResponse(status=200, body={"composeExtension": {"type": "result"}}))

    response = _client(handler).post("/teams/messages", json={"type": "invoke", "name": "composeExtension/query"})

    assert response.status_code == 200
    assert response.json() == {"composeExtension": {"type": "result"}}


def test_message_activities_get_a_bare_200():
    handler = _handler()
    handler._adapter.process_activity = AsyncMock(return_value=None)

    response = _client(handler).post("/teams/messages", json={"type": "message"})

    assert response.status_code == 200
    assert response.content == b""


def test_malformed_body_is_a_400():
    handler = _handler()
    handler._adapter.process_activity = AsyncMock(side_effect=AssertionError("must not reach the adapter"))

    response = _client(handler).post("/teams/messages", content=b"not json", headers={"Content-Type": "application/json"})

    assert response.status_code == 400
