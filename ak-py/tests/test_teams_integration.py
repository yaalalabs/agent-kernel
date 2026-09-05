"""Teams adapter: Bot Framework activity -> InboundRequest, and agent reply -> proactive delivery."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytest.importorskip("botbuilder.core")

from botbuilder.schema import Activity, ActivityTypes  # noqa: E402

from agentkernel.core.config import AKConfig  # noqa: E402
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestFile, AgentRequestImage, AgentRequestText  # noqa: E402
from agentkernel.integration.adapter.producer import IntegrationProducer  # noqa: E402
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler  # noqa: E402
from agentkernel.integration.teams.adapter import (  # noqa: E402
    FILE_DOWNLOAD_INFO,
    MAX_MESSAGE_LENGTH,
    TeamsInboundAdapter,
    TeamsOutboundAdapter,
    _AttachmentTooLarge,
    _TeamsCredentials,
)
from agentkernel.pipeline.transport.in_memory import InMemoryTransport  # noqa: E402

BOT_ID = "28:bot-app-id"
BOT_NAME = "AgentBot"


class FakeTurnContext:
    """Records the activities the adapter sends back to Teams."""

    def __init__(self, activity=None):
        self.activity = activity
        self.sent = []

    async def send_activity(self, activity):
        self.sent.append(activity)
        return {"id": "sent"}

    @property
    def texts(self):
        return [a for a in self.sent if isinstance(a, str)]


def _credentials(tenant_id=""):
    """Real credentials object, minus the Azure adapter construction."""
    credentials = object.__new__(_TeamsCredentials)
    credentials._app_id = "app-id"
    credentials._app_password = "app-password"
    credentials._tenant_id = tenant_id
    credentials._adapter = MagicMock()
    credentials._adapter.continue_conversation = AsyncMock()
    credentials._msal_apps = {}
    credentials._bot_credentials = None
    return credentials


def _inbound(agent="helper", tenant_id="", max_file_size=10 * 1024 * 1024):
    """Build the inbound adapter without running __init__ (no Azure adapter, no config)."""
    adapter = object.__new__(TeamsInboundAdapter)
    adapter._agent = agent
    adapter._max_file_size = max_file_size
    adapter._credentials = _credentials(tenant_id)
    return adapter


def _outbound(ack=None, tenant_id=""):
    adapter = object.__new__(TeamsOutboundAdapter)
    adapter._acknowledgement = ack
    adapter._credentials = _credentials(tenant_id)
    return adapter


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


async def _parse(adapter, activity):
    """Drive one turn the way the Bot Framework dispatch does, and return (request, turn context)."""
    turn_context = FakeTurnContext(activity)
    return await adapter._to_request(turn_context), turn_context


def _context(user_name="Alice"):
    """The reply context the inbound half produces for the default activity."""
    from botbuilder.core import TurnContext

    reference = TurnContext.get_conversation_reference(_activity())
    return {"conversation_reference": json.dumps(reference.serialize()), "user_name": user_name}


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


def test_akconfig_exposes_a_teams_block():
    """Regression for #619: the adapter reads Config.get().teams, which never existed."""
    config = AKConfig()
    assert config.teams.agent == ""
    assert config.teams.agent_acknowledgement == ""
    assert config.teams.app_id == ""
    assert config.teams.app_password == ""
    assert config.teams.tenant_id == ""
    assert config.teams.outbound_adapter == ""


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
async def test_a_message_becomes_a_normalized_request():
    request, _ = await _parse(_inbound(), _activity(channel_data={"channel": {"id": "19:channel-1"}}))

    assert request.prompt == "hello"
    assert request.agent == "helper"
    assert request.session_id == "conv-1"
    assert request.user_id == "user-1"
    assert request.group_id == "19:channel-1"
    assert request.request_id == "act-1", "the activity id is what dedupes an Azure redelivery"
    assert isinstance(request.requests[0], AgentRequestText) and request.requests[0].prompt == "hello"


@pytest.mark.asyncio
async def test_the_conversation_reference_travels_as_the_reply_context():
    """The reply is delivered from another process, so the whole reference has to cross the queue."""
    request, _ = await _parse(_inbound(), _activity())

    reference = json.loads(request.reply_context["conversation_reference"])
    assert reference["conversation"]["id"] == "conv-1"
    assert reference["serviceUrl"] == "https://smba.trafficmanager.net/emea/"
    assert request.reply_context["user_name"] == "Alice"


@pytest.mark.asyncio
async def test_non_message_activity_is_ignored():
    request, turn_context = await _parse(_inbound(), _activity(activity_type=ActivityTypes.conversation_update))

    assert request is None
    assert turn_context.sent == []


@pytest.mark.asyncio
async def test_empty_activity_is_dropped_without_a_reply():
    request, turn_context = await _parse(_inbound(), _activity(text=f"<at>{BOT_NAME}</at>"))

    assert request is None
    assert turn_context.sent == []


@pytest.mark.asyncio
async def test_a_post_whose_only_attachment_is_the_html_rendition_is_ignored():
    """Teams sends the message body twice: as text and as a text/html attachment. An @mention-only
    post therefore has no content at all, and is dropped silently rather than answered."""
    activity = _activity(text=f"<at>{BOT_NAME}</at>", attachments=[{"contentType": "text/html", "content": "<div>hi</div>"}])

    request, turn_context = await _parse(_inbound(), activity)

    assert request is None
    assert turn_context.sent == []


@pytest.mark.asyncio
async def test_a_sender_without_a_display_name_is_addressed_as_user():
    """Direct Line sends `from` with an id and no name, which would read as "Hi None, ..."."""
    activity = _activity()
    activity.from_property.name = None

    request, _ = await _parse(_inbound(), activity)

    assert request.reply_context["user_name"] == "User"


# --------------------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reply_is_delivered_proactively():
    adapter = _outbound()

    await adapter.deliver(AgentReplyText(response="agent says hi"), _context())

    reference, callback, bot_id = adapter._credentials.adapter.continue_conversation.await_args.args
    assert reference.conversation.id == "conv-1"
    assert bot_id == "app-id"
    turn_context = FakeTurnContext()
    await callback(turn_context)
    assert turn_context.texts == ["agent says hi"]


@pytest.mark.asyncio
async def test_a_structured_reply_is_delivered_as_json():
    adapter = _outbound()

    await adapter.deliver(AgentReplyAny(content={"a": 1}), _context())

    _, callback, _ = adapter._credentials.adapter.continue_conversation.await_args.args
    turn_context = FakeTurnContext()
    await callback(turn_context)
    assert turn_context.texts == ['{"a": 1}']


@pytest.mark.asyncio
async def test_an_empty_reply_says_so_rather_than_sending_nothing():
    adapter = _outbound()

    await adapter.deliver(AgentReplyText(response="   "), _context())

    _, callback, _ = adapter._credentials.adapter.continue_conversation.await_args.args
    turn_context = FakeTurnContext()
    await callback(turn_context)
    assert turn_context.texts == ["The agent returned an empty response."]


@pytest.mark.asyncio
async def test_a_long_reply_is_chunked_instead_of_dropped():
    adapter = _outbound()

    await adapter.deliver(AgentReplyText(response="x" * (MAX_MESSAGE_LENGTH * 2 + 5)), _context())

    assert adapter._credentials.adapter.continue_conversation.await_count == 3


@pytest.mark.asyncio
async def test_a_delivery_failure_propagates_for_retry():
    adapter = _outbound()
    adapter._credentials.adapter.continue_conversation = AsyncMock(side_effect=RuntimeError("azure down"))

    with pytest.raises(RuntimeError):
        await adapter.deliver(AgentReplyText(response="hi"), _context())


@pytest.mark.asyncio
async def test_the_acknowledgement_is_addressed_to_the_sender():
    adapter = _outbound(ack="I'm looking into that for you...")

    assert await adapter.acknowledge(_context()) == {}

    _, callback, _ = adapter._credentials.adapter.continue_conversation.await_args.args
    turn_context = FakeTurnContext()
    await callback(turn_context)
    assert turn_context.texts == ["Hi Alice, I'm looking into that for you..."]


@pytest.mark.asyncio
async def test_no_acknowledgement_is_sent_when_none_is_configured():
    adapter = _outbound()
    await adapter.acknowledge(_context())
    adapter._credentials.adapter.continue_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_error_reaches_the_user_by_name():
    adapter = _outbound()

    await adapter.deliver_error(TeamsOutboundAdapter.ERROR_MESSAGE, _context())

    _, callback, _ = adapter._credentials.adapter.continue_conversation.await_args.args
    turn_context = FakeTurnContext()
    await callback(turn_context)
    assert turn_context.texts == ["Sorry Alice, sorry, there was an error processing your request."]


@pytest.mark.asyncio
async def test_an_error_delivery_failure_does_not_escape():
    """A best-effort status message must not take down the consumer thread."""
    adapter = _outbound()
    adapter._credentials.adapter.continue_conversation = AsyncMock(side_effect=RuntimeError("azure down"))

    await adapter.deliver_error("boom", _context())


def test_split_reply_chunks_on_the_teams_limit():
    adapter = _outbound()

    assert len(adapter.split_reply("x" * MAX_MESSAGE_LENGTH)) == 1
    assert len(adapter.split_reply("x" * (MAX_MESSAGE_LENGTH + 1))) == 2


# --------------------------------------------------------------------------------------
# Mention handling
# --------------------------------------------------------------------------------------


def test_strip_mentions_removes_only_the_bot_mention():
    activity = _activity(
        text=f'<at id="0">{BOT_NAME}</at> please tell <at id="1">Bob</at> it is done',
        entities=[
            {"type": "mention", "text": f'<at id="0">{BOT_NAME}</at>', "mentioned": {"id": BOT_ID, "name": BOT_NAME}},
            {"type": "mention", "text": '<at id="1">Bob</at>', "mentioned": {"id": "29:bob", "name": "Bob"}},
        ],
    )

    assert _inbound()._strip_mentions(activity) == "please tell Bob it is done"


def test_strip_mentions_preserves_emails_and_handles():
    activity = _activity(text=f"<at>{BOT_NAME}</at> email billing@contoso.com and explain @staticmethod")

    assert _inbound()._strip_mentions(activity) == "email billing@contoso.com and explain @staticmethod"


def test_strip_mentions_preserves_newlines():
    activity = _activity(text=f"<at>{BOT_NAME}</at> review this:\n\n    def f():\n        pass")

    assert _inbound()._strip_mentions(activity) == "review this:\n\n    def f():\n        pass"


def test_strip_mentions_handles_the_id_carrying_tag_without_entities():
    activity = _activity(text=f'<at id="0">{BOT_NAME}</at> hello', entities=[])

    assert _inbound()._strip_mentions(activity) == "hello"


# --------------------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------------------


def _file_attachment(name="report.pdf", url="https://contoso.sharepoint.com/x?tempauth=jwt", file_type="pdf"):
    return {
        "contentType": FILE_DOWNLOAD_INFO,
        "name": name,
        "content": {"downloadUrl": url, "fileType": file_type, "uniqueId": "u1"},
    }


@pytest.fixture
def multimodal(monkeypatch):
    """Attachments cannot ride the queue as bytes, so they need a store."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
    monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
    AKConfig._reset()
    yield
    AKConfig._reset()


@pytest.mark.asyncio
async def test_uploaded_file_is_stored_and_referenced(multimodal):
    adapter = _inbound()
    adapter._download = AsyncMock(return_value=(b"%PDF-1.4", "application/pdf"))

    request, _ = await _parse(adapter, _activity(attachments=[_file_attachment()]))

    assert [r.type for r in request.requests] == ["text", "attachment_ref"]
    assert not any(isinstance(r, AgentRequestFile) for r in request.requests), "raw bytes must not reach the queue"


@pytest.mark.asyncio
async def test_an_attachment_without_multimodal_storage_is_a_configuration_error():
    adapter = _inbound()
    adapter._download = AsyncMock(return_value=(b"%PDF-1.4", "application/pdf"))

    with pytest.raises(ValueError, match="multimodal.enabled"):
        await _parse(adapter, _activity(attachments=[_file_attachment()]))


@pytest.mark.asyncio
async def test_inline_image_is_authorized_with_a_bot_framework_token(multimodal):
    """Inline images live on the Bot Connector and 401 without the bot's own token."""
    adapter = _inbound()
    adapter._credentials.bot_framework_token = AsyncMock(return_value="bf-token")
    captured = {}

    async def fake_download(url, headers):
        captured["url"] = url
        captured["headers"] = headers
        return b"\x89PNG", "image/png"

    adapter._download = fake_download
    activity = _activity(
        text=f"<at>{BOT_NAME}</at> what is this",
        attachments=[{"contentType": "image/*", "contentUrl": "https://smba.trafficmanager.net/emea/v3/attachments/1/views/original"}],
    )

    request, _ = await _parse(adapter, activity)

    assert captured["headers"] == {"Authorization": "Bearer bf-token"}
    assert [r.type for r in request.requests] == ["text", "attachment_ref"]


@pytest.mark.asyncio
async def test_an_inline_images_type_and_name_are_resolved_before_storage():
    """A Teams inline image declares only "image/*" and carries no name; both come from the download."""
    from botbuilder.schema import Attachment

    adapter = _inbound()
    adapter._credentials.bot_framework_token = AsyncMock(return_value="bf-token")
    adapter._download = AsyncMock(return_value=(b"\x89PNG", "image/png"))
    attachment = Attachment().deserialize({"contentType": "image/*", "contentUrl": "https://smba.trafficmanager.net/emea/v3/attachments/1"})
    requests = []

    await adapter._process_attachments([attachment], requests, "tenant-1")

    assert isinstance(requests[0], AgentRequestImage)
    assert requests[0].mime_type == "image/png"
    assert requests[0].name == "image.png"


@pytest.mark.asyncio
async def test_audio_and_video_are_rejected_before_any_download():
    adapter = _inbound()
    adapter._download = AsyncMock(side_effect=AssertionError("must not download rejected media"))

    request, turn_context = await _parse(adapter, _activity(attachments=[_file_attachment(name="demo.mp4", file_type="mp4")]))

    assert request is None
    assert "audio/video files were rejected" in turn_context.texts[-1]
    assert "demo.mp4" in turn_context.texts[-1]


@pytest.mark.asyncio
async def test_oversized_file_gets_its_own_message():
    adapter = _inbound()
    adapter._download = AsyncMock(side_effect=_AttachmentTooLarge(50 * 1024 * 1024))

    request, turn_context = await _parse(adapter, _activity(attachments=[_file_attachment(name="big.zip", file_type="zip")]))

    assert request is None
    assert "exceed the maximum size" in turn_context.texts[-1]
    assert "big.zip (50.00 MB)" in turn_context.texts[-1]


@pytest.mark.asyncio
async def test_download_failure_is_reported_as_a_download_failure():
    adapter = _inbound()
    adapter._download = AsyncMock(return_value=(None, None))

    request, turn_context = await _parse(adapter, _activity(attachments=[_file_attachment()]))

    assert request is None
    assert turn_context.texts[-1] == "Sorry Alice, I could not download the following files: report.pdf. Please try again."


@pytest.mark.asyncio
async def test_authorization_failure_is_reported_separately_from_a_download_failure():
    adapter = _inbound()
    adapter._download = AsyncMock(side_effect=AssertionError("must not download without authorization"))
    activity = _activity(attachments=[_file_attachment(url="https://contoso.sharepoint.com/download.aspx?UniqueId=1")])
    activity.conversation.tenant_id = None

    request, turn_context = await _parse(adapter, activity)

    assert request is None
    assert "not allowed to download" in turn_context.texts[-1]
    assert "contact your administrator" in turn_context.texts[-1]


# --------------------------------------------------------------------------------------
# Download authorization
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_authenticated_url_gets_no_authorization_header():
    assert await _inbound()._download_headers("https://contoso.sharepoint.com/x?tempauth=jwt", "tenant-1") == {}


@pytest.mark.asyncio
async def test_unknown_host_is_never_handed_a_bearer_token():
    adapter = _inbound()
    adapter._credentials.acquire_token = MagicMock(side_effect=AssertionError("must not mint a token for an unknown host"))

    assert await adapter._download_headers("https://evil.example.com/steal", "tenant-1") == {}


@pytest.mark.asyncio
async def test_sharepoint_download_uses_a_tenant_scoped_app_only_token():
    adapter = _inbound()
    adapter._credentials.acquire_token = MagicMock(return_value={"access_token": "spo-token"})

    headers = await adapter._download_headers("https://contoso.sharepoint.com/download.aspx?UniqueId=1", "tenant-1")

    assert headers == {"Authorization": "Bearer spo-token"}
    adapter._credentials.acquire_token.assert_called_once_with("tenant-1", "https://contoso.sharepoint.com/.default")


@pytest.mark.asyncio
async def test_app_only_token_is_refused_without_a_tenant():
    """The client credentials grant is not valid against the /common authority."""
    with pytest.raises(PermissionError, match="teams.tenant_id"):
        await _inbound()._download_headers("https://contoso.sharepoint.com/download.aspx?UniqueId=1", None)


@pytest.mark.asyncio
async def test_token_acquisition_failure_raises_instead_of_falling_through():
    adapter = _inbound()
    adapter._credentials.acquire_token = MagicMock(return_value={"error": "invalid_client", "error_description": "AADSTS7000215"})

    with pytest.raises(PermissionError, match="AADSTS7000215"):
        await adapter._download_headers("https://contoso.sharepoint.com/download.aspx?UniqueId=1", "tenant-1")


def test_resolve_tenant_prefers_the_activity_over_the_configuration():
    """A client credentials grant needs the customer's tenant, not the bot's home tenant."""
    credentials = _credentials(tenant_id="configured-tenant")

    assert credentials.resolve_tenant(_activity()) == "tenant-from-activity"

    # Teams itself sends the tenant in channelData; the adapter copies it onto the
    # conversation, so the raw channelData is the fallback.
    activity = _activity(channel_data={"tenant": {"id": "channel-data-tenant"}})
    activity.conversation.tenant_id = None
    assert credentials.resolve_tenant(activity) == "channel-data-tenant"

    activity.channel_data = None
    assert credentials.resolve_tenant(activity) == "configured-tenant"

    assert _credentials(tenant_id="").resolve_tenant(activity) is None


@pytest.mark.asyncio
async def test_bot_framework_credentials_carry_the_bots_own_tenant(monkeypatch):
    """A single-tenant registration cannot mint a connector token against the default authority."""
    built = []

    class RecordingCredentials:
        def __init__(self, app_id, password, channel_auth_tenant=None):
            built.append((app_id, password, channel_auth_tenant))

        def get_access_token(self):
            return "bf-token"

    monkeypatch.setattr("agentkernel.integration.teams.adapter.MicrosoftAppCredentials", RecordingCredentials)

    assert await _credentials(tenant_id="bot-home-tenant").bot_framework_token() == "bf-token"
    assert built == [("app-id", "app-password", "bot-home-tenant")]

    # A multi-tenant registration has no tenant of its own and must keep the SDK default authority.
    built.clear()
    await _credentials(tenant_id="").bot_framework_token()
    assert built == [("app-id", "app-password", None)]


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
    _mock_httpx(monkeypatch, lambda request: httpx.Response(200, content=b"hello", headers={"content-type": "application/pdf; charset=utf-8"}))

    data, content_type = await _inbound()._download("https://host/file", {})

    assert data == b"hello"
    assert content_type == "application/pdf"


@pytest.mark.asyncio
async def test_download_reports_a_non_200_as_a_failure(monkeypatch):
    _mock_httpx(monkeypatch, lambda request: httpx.Response(401, content=b"denied"))

    assert await _inbound()._download("https://host/file", {}) == (None, None)


@pytest.mark.asyncio
async def test_download_rejects_an_oversized_body_from_content_length(monkeypatch):
    _mock_httpx(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 64))

    with pytest.raises(_AttachmentTooLarge):
        await _inbound(max_file_size=8)._download("https://host/file", {})


@pytest.mark.asyncio
async def test_download_aborts_a_chunked_body_that_grows_past_the_limit(monkeypatch):
    """Without a content-length the cap has to be enforced while streaming."""

    def responder(request):
        async def chunks():
            for _ in range(10):
                yield b"xxxx"

        return httpx.Response(200, content=chunks())

    _mock_httpx(monkeypatch, responder)

    with pytest.raises(_AttachmentTooLarge):
        await _inbound(max_file_size=8)._download("https://host/file", {})


# --------------------------------------------------------------------------------------
# Webhook route
# --------------------------------------------------------------------------------------


def _client(adapter):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    handler = WebhookRESTRequestHandler(adapter, producer=IntegrationProducer(InMemoryTransport()))
    app = FastAPI()
    app.include_router(handler.get_router())
    return TestClient(app, raise_server_exceptions=False)


def test_failed_bot_framework_auth_returns_401_not_500():
    """Azure retries 5xx, so a rejected JWT must not be reported as a server error."""
    adapter = _inbound()
    adapter._credentials.adapter.process_activity = AsyncMock(side_effect=PermissionError("Unauthorized Access."))

    assert _client(adapter).post("/teams/messages", json={"type": "message"}).status_code == 401


def test_unexpected_failure_still_returns_500():
    adapter = _inbound()
    adapter._credentials.adapter.process_activity = AsyncMock(side_effect=RuntimeError("boom"))

    assert _client(adapter).post("/teams/messages", json={"type": "message"}).status_code == 500


def test_invoke_activities_get_their_invoke_response_body():
    from botbuilder.schema import InvokeResponse

    adapter = _inbound()
    adapter._credentials.adapter.process_activity = AsyncMock(return_value=InvokeResponse(status=200, body={"composeExtension": {"type": "result"}}))

    response = _client(adapter).post("/teams/messages", json={"type": "invoke", "name": "composeExtension/query"})

    assert response.status_code == 200
    assert response.json() == {"composeExtension": {"type": "result"}}


def test_message_activities_get_the_hosts_success_body():
    adapter = _inbound()
    adapter._credentials.adapter.process_activity = AsyncMock(return_value=None)

    response = _client(adapter).post("/teams/messages", json={"type": "message"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_malformed_body_is_a_400():
    adapter = _inbound()
    adapter._credentials.adapter.process_activity = AsyncMock(side_effect=AssertionError("must not reach the adapter"))

    response = _client(adapter).post("/teams/messages", content=b"not json", headers={"Content-Type": "application/json"})

    assert response.status_code == 400


def test_logging_name_is_stable():
    assert logging.getLogger("ak.integration.teams") is TeamsInboundAdapter._log
