"""Every built-in adapter pair against the shared IntegrationAdapterContract.

The contract asserts what the queue hop needs from any adapter — stable identifiers, an ignorable
delivery that is not an error, a flat reply context inside its budget, a clean round trip through
the producer. Each platform's own parsing and formatting stays in its own test file.
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.integration.adapter.base import InboundParseResult
from agentkernel.integration.adapter.testing import IntegrationAdapterContract

APP_SECRET = "app-secret"


def _fake_request(body, headers=None, query=None):
    payload = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
    request = MagicMock()
    request.headers = headers or {}
    request.query_params = query or {}
    request.body = AsyncMock(return_value=payload)
    request.json = AsyncMock(return_value=json.loads(payload) if payload else {})
    return request


def _signed(body, secret=APP_SECRET):
    payload = json.dumps(body).encode()
    return _fake_request(payload, headers={"x-hub-signature-256": "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()})


class _ConfiguredContract(IntegrationAdapterContract):
    """Base for the built-ins: gives each platform the credentials its adapters demand."""

    ENV: dict = {}

    @pytest.fixture(autouse=True)
    def _platform_config(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        for key, value in self.ENV.items():
            monkeypatch.setenv(key, value)
        AKConfig._reset()
        yield
        AKConfig._reset()


class TestWhatsAppContract(_ConfiguredContract):
    ENV = {
        "AK_WHATSAPP__ACCESS_TOKEN": "token",
        "AK_WHATSAPP__PHONE_NUMBER_ID": "phone-1",
        "AK_WHATSAPP__VERIFY_TOKEN": "verify-me",
        "AK_WHATSAPP__APP_SECRET": APP_SECRET,
    }

    def make_inbound(self):
        from agentkernel.integration.whatsapp.adapter import WhatsAppInboundAdapter

        return WhatsAppInboundAdapter()

    def make_outbound(self):
        from agentkernel.integration.whatsapp.adapter import WhatsAppOutboundAdapter

        return WhatsAppOutboundAdapter()

    def valid_delivery(self):
        message = {"id": "wamid.1", "from": "15551234567", "type": "text", "text": {"body": "hello"}}
        return _signed({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [message]}}]}]})

    def ignorable_delivery(self):
        return _signed({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]})

    def unauthentic_delivery(self):
        return _fake_request(b"{}", headers={"x-hub-signature-256": "sha256=deadbeef"})

    expected_session_id = "15551234567"
    expected_request_id = "wamid.1"


class TestMessengerContract(_ConfiguredContract):
    ENV = {
        "AK_MESSENGER__ACCESS_TOKEN": "token",
        "AK_MESSENGER__VERIFY_TOKEN": "verify-me",
        "AK_MESSENGER__APP_SECRET": APP_SECRET,
    }

    def make_inbound(self):
        from agentkernel.integration.messenger.adapter import MessengerInboundAdapter

        return MessengerInboundAdapter()

    def make_outbound(self):
        from agentkernel.integration.messenger.adapter import MessengerOutboundAdapter

        return MessengerOutboundAdapter()

    def valid_delivery(self):
        event = {"sender": {"id": "psid-123"}, "message": {"mid": "mid.1", "text": "hello"}}
        return _signed({"object": "page", "entry": [{"messaging": [event]}]})

    def ignorable_delivery(self):
        return _signed({"object": "page", "entry": [{"messaging": [{"sender": {"id": "psid-123"}, "delivery": {"watermark": 1}}]}]})

    def unauthentic_delivery(self):
        return _fake_request(b"{}", headers={"x-hub-signature-256": "sha256=deadbeef"})

    expected_session_id = "psid-123"
    expected_request_id = "mid.1"


class TestInstagramContract(_ConfiguredContract):
    ENV = {
        "AK_INSTAGRAM__ACCESS_TOKEN": "token",
        "AK_INSTAGRAM__VERIFY_TOKEN": "verify-me",
        "AK_INSTAGRAM__APP_SECRET": APP_SECRET,
    }

    def make_inbound(self):
        from agentkernel.integration.instagram.adapter import InstagramInboundAdapter

        return InstagramInboundAdapter()

    def make_outbound(self):
        from agentkernel.integration.instagram.adapter import InstagramOutboundAdapter

        return InstagramOutboundAdapter()

    def valid_delivery(self):
        event = {"sender": {"id": "igsid-123"}, "message": {"mid": "mid.1", "text": "hello"}}
        return _signed({"object": "instagram", "entry": [{"messaging": [event]}]})

    def ignorable_delivery(self):
        event = {"sender": {"id": "igsid-123"}, "message": {"mid": "mid.1", "text": "echo", "is_echo": True}}
        return _signed({"object": "instagram", "entry": [{"messaging": [event]}]})

    def unauthentic_delivery(self):
        return _fake_request(b"{}", headers={"x-hub-signature-256": "sha256=deadbeef"})

    expected_session_id = "igsid-123"
    expected_request_id = "mid.1"


class TestTelegramContract(_ConfiguredContract):
    ENV = {"AK_TELEGRAM__BOT_TOKEN": "bot-token", "AK_TELEGRAM__WEBHOOK_SECRET": "webhook-secret"}

    def make_inbound(self):
        from agentkernel.integration.telegram.adapter import TelegramInboundAdapter

        return TelegramInboundAdapter()

    def make_outbound(self):
        from agentkernel.integration.telegram.adapter import TelegramOutboundAdapter

        return TelegramOutboundAdapter()

    def valid_delivery(self):
        update = {"update_id": 100, "message": {"message_id": 7, "chat": {"id": 4242}, "from": {"id": 99}, "text": "hello"}}
        return _fake_request(update, headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"})

    def ignorable_delivery(self):
        return _fake_request({"update_id": 101, "poll": {}}, headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"})

    def unauthentic_delivery(self):
        return _fake_request(b"{}", headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})

    expected_session_id = "4242"
    expected_request_id = "100"


class TestGmailContract(_ConfiguredContract):
    ENV = {"AK_GMAIL__CLIENT_ID": "client-id", "AK_GMAIL__CLIENT_SECRET": "client-secret"}

    @staticmethod
    def _gmail_client():
        body = base64.urlsafe_b64encode(b"Hello agent").decode()
        message = {
            "id": "msg-1",
            "threadId": "thread-1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Greetings"},
                    {"name": "Message-ID", "value": "<orig@mail>"},
                ],
                "body": {"data": body},
            },
        }
        client = MagicMock()
        users = client.users.return_value
        users.messages.return_value.get.return_value.execute.return_value = message
        users.threads.return_value.get.return_value.execute.return_value = {"messages": []}
        return client

    def make_inbound(self):
        from agentkernel.integration.gmail.adapter import GmailInboundAdapter

        adapter = GmailInboundAdapter()
        adapter._service._service = self._gmail_client()
        return adapter

    def make_outbound(self):
        from agentkernel.integration.gmail.adapter import GmailOutboundAdapter

        return GmailOutboundAdapter()

    def valid_delivery(self):
        return "msg-1"

    expected_session_id = "thread-1"
    expected_request_id = "msg-1"


class TestSlackContract(_ConfiguredContract):
    """Slack's dispatch belongs to Bolt, so the contract drives the normalization it wraps."""

    ENV = {"SLACK_BOT_TOKEN": "xoxb-test-token", "SLACK_SIGNING_SECRET": "signing-secret"}

    def make_inbound(self):
        from agentkernel.integration.slack.adapter import SlackInboundAdapter

        adapter = object.__new__(SlackInboundAdapter)
        adapter._agent = None
        adapter._max_file_size = 10 * 1024 * 1024
        adapter._bot_id = "B_BOT"
        adapter._app = MagicMock()
        adapter._app.client.chat_postMessage = AsyncMock()
        return adapter

    def make_outbound(self):
        from agentkernel.integration.slack.adapter import SlackOutboundAdapter

        return SlackOutboundAdapter()

    def valid_delivery(self):
        return {"user": "U123", "text": "hello", "channel": "C9", "ts": "111.222"}

    def ignorable_delivery(self):
        return {"user": "B_BOT", "text": "the bot's own message", "channel": "C9", "ts": "111.222"}

    async def _parse_valid(self) -> InboundParseResult:
        adapter = self.make_inbound()
        request = await adapter._to_request(self.valid_delivery())
        return InboundParseResult(requests=[request] if request else [])

    @pytest.mark.asyncio
    async def test_an_ignorable_delivery_is_not_an_error(self):
        adapter = self.make_inbound()
        assert await adapter._to_request(self.ignorable_delivery()) is None

    expected_session_id = "111.222"
    expected_request_id = "slack:C9:111.222"


class TestTeamsContract(_ConfiguredContract):
    """Teams' dispatch belongs to the Bot Framework, so the contract drives the turn it wraps."""

    ENV = {"AK_TEAMS__APP_ID": "app-id", "AK_TEAMS__APP_PASSWORD": "app-password"}

    def make_inbound(self):
        from agentkernel.integration.teams.adapter import TeamsInboundAdapter

        adapter = object.__new__(TeamsInboundAdapter)
        adapter._agent = None
        adapter._max_file_size = 10 * 1024 * 1024
        adapter._credentials = self._credentials()
        return adapter

    def make_outbound(self):
        from agentkernel.integration.teams.adapter import TeamsOutboundAdapter

        adapter = object.__new__(TeamsOutboundAdapter)
        adapter._acknowledgement = None
        adapter._credentials = self._credentials()
        return adapter

    @staticmethod
    def _credentials():
        from agentkernel.integration.teams.adapter import _TeamsCredentials

        credentials = object.__new__(_TeamsCredentials)
        credentials._app_id = "app-id"
        credentials._app_password = "app-password"
        credentials._tenant_id = ""
        credentials._adapter = MagicMock()
        credentials._msal_apps = {}
        credentials._bot_credentials = None
        return credentials

    @staticmethod
    def _turn_context(activity_type="message"):
        from botbuilder.schema import Activity

        activity = Activity().deserialize(
            {
                "type": activity_type,
                "id": "act-1",
                "text": "hello",
                "from": {"id": "user-1", "name": "Alice"},
                "conversation": {"id": "conv-1"},
                "recipient": {"id": "28:bot", "name": "AgentBot"},
                "serviceUrl": "https://smba.trafficmanager.net/emea/",
            }
        )
        turn_context = MagicMock()
        turn_context.activity = activity
        turn_context.send_activity = AsyncMock()
        return turn_context

    def valid_delivery(self):
        return self._turn_context()

    async def _parse_valid(self) -> InboundParseResult:
        request = await self.make_inbound()._to_request(self.valid_delivery())
        return InboundParseResult(requests=[request] if request else [])

    @pytest.mark.asyncio
    async def test_an_ignorable_delivery_is_not_an_error(self):
        assert await self.make_inbound()._to_request(self._turn_context("conversationUpdate")) is None

    expected_session_id = "conv-1"
    expected_request_id = "act-1"
