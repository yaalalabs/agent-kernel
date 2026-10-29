"""Slack adapter: platform event -> InboundRequest, and agent reply -> Slack messages."""

import hashlib
import hmac
import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("slack_bolt")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agentkernel.core.config import AKConfig  # noqa: E402
from agentkernel.core.event import PausedInterruption  # noqa: E402
from agentkernel.core.model import (  # noqa: E402
    AgentPausedReplyAny,
    AgentReplyText,
    AgentRequestAny,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
)
from agentkernel.integration.adapter.producer import IntegrationProducer  # noqa: E402
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler  # noqa: E402
from agentkernel.integration.slack.adapter import (  # noqa: E402
    ACTION_PREFIX,
    BLOCK_PREFIX,
    MAX_BLOCKS,
    MODAL_CALLBACK_ID,
    REASON_BLOCK_ID,
    REASON_INPUT_ID,
    REASON_PREFIX,
    SlackInboundAdapter,
    SlackOutboundAdapter,
)
from agentkernel.pipeline.envelope import QueueName  # noqa: E402
from agentkernel.pipeline.transport.in_memory import InMemoryTransport  # noqa: E402

BOT_ID = "B_BOT"
SIGNING_SECRET = "test-signing-secret"


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    AKConfig._reset()
    InMemoryTransport.reset()
    yield
    InMemoryTransport.reset()
    AKConfig._reset()


def _inbound(agent="helper", max_file_size=10 * 1024 * 1024):
    """Build the adapter without Bolt, for the parsing tests."""
    adapter = object.__new__(SlackInboundAdapter)
    adapter._agent = agent
    adapter._max_file_size = max_file_size
    adapter._bot_id = BOT_ID
    adapter._app = MagicMock()
    adapter._app.client.chat_postMessage = AsyncMock()
    adapter._app.client.token = "xoxb-test-token"
    return adapter


def _outbound(acknowledgement=None):
    adapter = object.__new__(SlackOutboundAdapter)
    adapter._acknowledgement = acknowledgement
    return adapter


def _event(text=f"hello <@{BOT_ID}>", user="U123", channel="C9", ts="111.222", thread_ts=None, files=None):
    event = {"user": user, "text": text, "channel": channel, "ts": ts}
    if thread_ts:
        event["thread_ts"] = thread_ts
    if files:
        event["files"] = files
    return event


class TestParse:
    @pytest.mark.asyncio
    async def test_a_message_becomes_a_normalized_request(self):
        request = await _inbound()._to_request(_event(thread_ts="000.111"))

        assert request.prompt == "hello"
        assert request.agent == "helper"
        assert request.user_id == "U123"
        assert request.group_id == "C9"
        # Slack's session key is the thread, so a threaded reply continues the conversation.
        assert request.session_id == "000.111"
        assert request.reply_context == {"channel": "C9", "thread_ts": "000.111", "user": "U123"}

    @pytest.mark.asyncio
    async def test_an_unthreaded_message_starts_its_own_thread(self):
        assert (await _inbound()._to_request(_event())).session_id == "111.222"

    @pytest.mark.asyncio
    async def test_the_request_id_dedupes_a_slack_retry(self):
        # Bolt hands over the inner event, not the envelope, so there is no Slack id to use;
        # channel plus ts is unique per message.
        assert (await _inbound()._to_request(_event())).request_id == "C9:111.222"

    @pytest.mark.asyncio
    async def test_the_event_body_travels_as_agent_context(self):
        request = await _inbound()._to_request(_event())
        text, body = request.requests
        assert isinstance(text, AgentRequestText) and text.prompt == "hello"
        assert isinstance(body, AgentRequestAny) and body.name == "body"

    @pytest.mark.asyncio
    async def test_the_bots_own_message_is_ignored(self):
        assert await _inbound()._to_request(_event(user=BOT_ID)) is None

    @pytest.mark.asyncio
    async def test_an_empty_message_is_ignored_with_a_nudge(self):
        adapter = _inbound()
        assert await adapter._to_request(_event(text=f"<@{BOT_ID}>")) is None
        assert "Please provide a message or attachment." in adapter._app.client.chat_postMessage.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_audio_and_video_are_rejected_at_the_edge(self):
        adapter = _inbound()
        files = [{"name": "clip.mp4", "mimetype": "video/mp4", "size": 10}]
        assert await adapter._to_request(_event(files=files)) is None
        assert "clip.mp4" in adapter._app.client.chat_postMessage.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_an_oversized_file_is_rejected_at_the_edge(self):
        adapter = _inbound(max_file_size=10)
        files = [{"name": "big.pdf", "mimetype": "application/pdf", "size": 5_000_000}]
        assert await adapter._to_request(_event(files=files)) is None
        assert "big.pdf" in adapter._app.client.chat_postMessage.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_a_download_failure_stops_the_run(self, monkeypatch):
        adapter = _inbound()
        monkeypatch.setattr(adapter, "_download", AsyncMock(return_value=None))
        files = [{"name": "doc.pdf", "mimetype": "application/pdf", "size": 10, "url_private": "https://files.slack/doc"}]
        assert await adapter._to_request(_event(files=files)) is None
        assert "could not download" in adapter._app.client.chat_postMessage.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_an_attachment_needs_multimodal_storage(self, monkeypatch):
        # Bytes cannot ride the queue, so an attachment without a store is a configuration error
        # rather than a silently dropped file.
        adapter = _inbound()
        monkeypatch.setattr(adapter, "_download", AsyncMock(return_value=b"\x89PNG"))
        files = [{"name": "shot.png", "mimetype": "image/png", "size": 10, "url_private": "https://files.slack/shot"}]
        with pytest.raises(ValueError, match="multimodal.enabled"):
            await adapter._to_request(_event(files=files))

    @pytest.mark.asyncio
    async def test_an_attachment_travels_as_a_stored_reference(self, monkeypatch):
        monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
        monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
        AKConfig._reset()
        adapter = _inbound()
        monkeypatch.setattr(adapter, "_download", AsyncMock(return_value=b"\x89PNG"))
        files = [{"name": "shot.png", "mimetype": "image/png", "size": 10, "url_private": "https://files.slack/shot"}]

        request = await adapter._to_request(_event(files=files))

        types = [r.type for r in request.requests]
        assert types == ["text", "attachment_ref", "other"]
        assert not any(isinstance(r, AgentRequestImage) for r in request.requests), "raw bytes must not reach the queue"


class TestBoltDispatch:
    """Bolt owns verification and the HTTP response; parse runs it and hands the response back."""

    @staticmethod
    def _post(client, body: dict, extra_headers: dict = None):
        payload = json.dumps(body)
        timestamp = str(int(time.time()))
        signature = "v0=" + hmac.new(SIGNING_SECRET.encode(), f"v0:{timestamp}:{payload}".encode(), hashlib.sha256).hexdigest()
        return client.post(
            "/slack/events",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                **(extra_headers or {}),
            },
        )

    @pytest.fixture(autouse=True)
    def _stub_auth_test(self, monkeypatch):
        """Bolt authorizes every request against auth.test; keep that off the network."""
        from slack_sdk.web.async_client import AsyncWebClient

        class _AuthTestResponse(dict):
            headers = {"x-oauth-scopes": "chat:write"}

        async def _auth_test(self, **kwargs):
            return _AuthTestResponse(ok=True, bot_id=BOT_ID, user_id=BOT_ID, team_id="T1", url="https://test.slack.com/")

        monkeypatch.setattr(AsyncWebClient, "auth_test", _auth_test)

    def _client(self, transport):
        adapter = SlackInboundAdapter()
        adapter._bot_id = BOT_ID  # the bot's own messages are skipped without a round trip
        app = FastAPI()
        app.include_router(WebhookRESTRequestHandler(adapter, producer=IntegrationProducer(transport)).get_router())
        return TestClient(app)

    def test_the_url_verification_handshake_is_answered_by_bolt(self):
        response = self._post(self._client(InMemoryTransport()), {"type": "url_verification", "challenge": "abc123"})
        assert response.status_code == 200
        assert "abc123" in response.text

    def test_an_unsigned_request_is_rejected(self):
        client = self._client(InMemoryTransport())
        response = client.post("/slack/events", json={"type": "event_callback"})
        assert response.status_code == 401

    def test_a_signed_message_event_is_enqueued(self):
        transport = InMemoryTransport()
        body = {"type": "event_callback", "team_id": "T1", "event": {**_event(), "type": "message", "channel_type": "channel"}}

        assert self._post(self._client(transport), body).status_code == 200

        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)
        assert message.attributes["integration"] == "slack"
        assert message.attributes["reply_channel"] == "C9"
        assert json.loads(message.body)["prompt"] == "hello"

    def test_a_timeout_retry_is_dropped_without_redispatching(self):
        """The first attempt finished out of band; re-running it would re-download and re-acknowledge."""
        transport = InMemoryTransport()
        body = {"type": "event_callback", "team_id": "T1", "event": {**_event(), "type": "message", "channel_type": "channel"}}
        headers = {"X-Slack-Retry-Num": "1", "X-Slack-Retry-Reason": "http_timeout"}

        assert self._post(self._client(transport), body, headers).status_code == 200

        assert transport.create_consumer(QueueName.INPUT).fetch(1, 0.1) == []

    def test_an_error_retry_still_runs(self):
        """http_error means this process genuinely failed the delivery, so the retry is the recovery."""
        transport = InMemoryTransport()
        body = {"type": "event_callback", "team_id": "T1", "event": {**_event(), "type": "message", "channel_type": "channel"}}
        headers = {"X-Slack-Retry-Num": "1", "X-Slack-Retry-Reason": "http_error"}

        assert self._post(self._client(transport), body, headers).status_code == 200

        assert len(transport.create_consumer(QueueName.INPUT).fetch(1, 1.0)) == 1


class TestDeliver:
    @pytest.mark.asyncio
    async def test_the_reply_is_posted_in_the_originating_thread(self, monkeypatch):
        client = MagicMock()
        client.chat_postMessage = AsyncMock()
        monkeypatch.setattr(SlackOutboundAdapter, "_client", staticmethod(lambda: client))

        await _outbound().deliver(AgentReplyText(response="agent says hi"), {"channel": "C9", "thread_ts": "000.111", "user": "U123"})

        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C9"
        assert kwargs["thread_ts"] == "000.111"
        assert kwargs["blocks"] == [{"type": "section", "text": {"type": "mrkdwn", "text": "agent says hi"}}]

    @pytest.mark.asyncio
    async def test_the_acknowledgement_is_cleared_before_the_reply(self, monkeypatch):
        client = MagicMock()
        client.chat_postMessage = AsyncMock()
        client.chat_update = AsyncMock()
        monkeypatch.setattr(SlackOutboundAdapter, "_client", staticmethod(lambda: client))

        context = {"channel": "C9", "thread_ts": "000.111", "user": "U123", "ack_ts": "ack-1", "ack_channel": "C9"}
        await _outbound().deliver(AgentReplyText(response="hi"), context)

        # The loading emoji is removed by editing the acknowledgement, as it always was.
        assert client.chat_update.call_args.kwargs == {"channel": "C9", "ts": "ack-1", "text": "Hi <@U123>,"}
        assert client.chat_postMessage.call_args.kwargs["thread_ts"] == "ack-1"

    @pytest.mark.asyncio
    async def test_the_acknowledgement_reports_where_it_landed(self, monkeypatch):
        client = MagicMock()
        client.chat_postMessage = AsyncMock(return_value={"ts": "ack-1", "channel": "C9"})
        monkeypatch.setattr(SlackOutboundAdapter, "_client", staticmethod(lambda: client))

        extra = await _outbound(acknowledgement="working on it").acknowledge({"channel": "C9", "thread_ts": "000.111", "user": "U123"})

        assert extra == {"ack_ts": "ack-1", "ack_channel": "C9"}
        assert ":rolling-loader:" in client.chat_postMessage.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_no_acknowledgement_is_posted_when_none_is_configured(self, monkeypatch):
        client = MagicMock()
        client.chat_postMessage = AsyncMock()
        monkeypatch.setattr(SlackOutboundAdapter, "_client", staticmethod(lambda: client))
        assert await _outbound().acknowledge({"channel": "C9"}) == {}
        client.chat_postMessage.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_error_reaches_the_user(self, monkeypatch):
        client = MagicMock()
        client.chat_postMessage = AsyncMock()
        monkeypatch.setattr(SlackOutboundAdapter, "_client", staticmethod(lambda: client))

        await _outbound().deliver_error("Sorry, something broke.", {"channel": "C9"})

        assert client.chat_postMessage.call_args.kwargs == {"channel": "C9", "text": "Sorry, something broke."}

    def test_a_long_reply_is_chunked_into_blocks(self):
        blocks = _outbound().split_reply("x" * 3001)
        assert [b["type"] for b in blocks] == ["section", "section"]
        assert len(blocks[0]["text"]["text"]) == 3000

    def test_an_enormous_reply_is_truncated_with_a_notice(self):
        blocks = _outbound().split_reply("x" * (3000 * 7))
        assert len(blocks) == 6
        assert blocks[-1]["text"]["text"] == SlackOutboundAdapter.TRUNCATION_NOTICE


def test_logging_name_is_stable():
    # Operators filter on this; it survived the move from handler to adapter.
    assert logging.getLogger("ak.integration.slack") is SlackInboundAdapter._log


def _paused(*interruption_ids):
    return AgentPausedReplyAny(
        run_id="01JD7K2MX4",
        session_id="000.111",
        agent="helper",
        interruptions=[
            PausedInterruption(id=i, kind="tool_call", tool_name="refund_order", arguments='{"order_id": "A-10294"}') for i in interruption_ids
        ],
    )


def _submission(reason, value="call_9f2b:denied"):
    metadata = {"value": value, "channel": "C9", "ts": "111.222", "thread_ts": "000.111", "user": "U123"}
    state = {"values": {REASON_BLOCK_ID: {REASON_INPUT_ID: {"value": reason}}}}
    return {"view": {"private_metadata": json.dumps(metadata), "state": state}}


def _press(value="call_9f2b:approved", channel="C9", message_ts="111.222", thread_ts="000.111", user="U123"):
    return {
        "actions": [{"action_id": f"{ACTION_PREFIX}approved", "value": value}],
        "channel": {"id": channel},
        "container": {"message_ts": message_ts, "thread_ts": thread_ts},
        "user": {"id": user},
    }


class TestPauseRendering:
    """A paused run drawn as Block Kit buttons."""

    @pytest.mark.asyncio
    async def test_each_interruption_gets_an_actions_block(self):
        adapter, posted = _outbound(), AsyncMock()
        with patch.object(SlackOutboundAdapter, "_client", return_value=MagicMock(chat_postMessage=posted)):
            await adapter.deliver_paused(_paused("call_a", "call_b"), {"channel": "C9", "thread_ts": "000.111"})

        blocks = posted.await_args.kwargs["blocks"]
        actions = [b for b in blocks if b["type"] == "actions"]
        assert [b["block_id"] for b in actions] == [f"{BLOCK_PREFIX}call_a", f"{BLOCK_PREFIX}call_b"]
        assert [e["value"] for e in actions[0]["elements"]] == ["call_a:approved", "call_a:denied"]
        assert [e["action_id"] for e in actions[0]["elements"]] == [f"{ACTION_PREFIX}approved", f"{REASON_PREFIX}denied"]
        assert [e.get("style") for e in actions[0]["elements"]] == ["primary", "danger"]
        assert any("refund_order" in str(b) for b in blocks if b["type"] == "section")

    @pytest.mark.asyncio
    async def test_a_third_verb_is_offered_when_the_adapter_declares_it(self):
        adapter, posted = _outbound(), AsyncMock()
        adapter.DECISIONS = ("approved", "denied", "cancelled")
        with patch.object(SlackOutboundAdapter, "_client", return_value=MagicMock(chat_postMessage=posted)):
            await adapter.deliver_paused(_paused("call_a"), {"channel": "C9"})

        [actions] = [b for b in posted.await_args.kwargs["blocks"] if b["type"] == "actions"]
        assert [e["text"]["text"] for e in actions["elements"]] == ["Approve", "Deny", "Cancel"]

    @pytest.mark.asyncio
    async def test_interruptions_past_the_block_budget_are_named_instead_of_dropped(self):
        adapter, posted = _outbound(), AsyncMock()
        with patch.object(SlackOutboundAdapter, "_client", return_value=MagicMock(chat_postMessage=posted)):
            await adapter.deliver_paused(_paused(*[f"call_{n}" for n in range(MAX_BLOCKS + 5)]), {"channel": "C9"})

        blocks = posted.await_args.kwargs["blocks"]
        assert len(blocks) <= MAX_BLOCKS, "Slack refuses a message over its block budget"
        [notice] = [b for b in blocks if b["type"] == "context"]
        assert "call_49" in notice["elements"][0]["text"], "an interruption without buttons must still be named"

    @pytest.mark.asyncio
    async def test_a_question_wanting_a_value_gets_no_buttons(self):
        adapter, posted = _outbound(), AsyncMock()
        reply = AgentPausedReplyAny(
            run_id="01JD7K2MX4",
            session_id="000.111",
            agent="helper",
            interruptions=[PausedInterruption(id="call_q", kind="input_required", message="Which warehouse?")],
        )
        with patch.object(SlackOutboundAdapter, "_client", return_value=MagicMock(chat_postMessage=posted)):
            await adapter.deliver_paused(reply, {"channel": "C9"})

        blocks = posted.await_args.kwargs["blocks"]
        assert not [b for b in blocks if b["type"] == "actions"], "Approve answers nothing when the agent asked for a value"
        assert any("Which warehouse?" in str(b) for b in blocks)

    @pytest.mark.asyncio
    async def test_a_mixed_pause_keeps_the_approval_buttons_and_names_the_question(self):
        adapter, posted = _outbound(), AsyncMock()
        reply = AgentPausedReplyAny(
            run_id="01JD7K2MX4",
            session_id="000.111",
            agent="helper",
            interruptions=[
                PausedInterruption(id="call_a", kind="tool_call", tool_name="refund_order"),
                PausedInterruption(id="call_q", kind="input_required", message="Which warehouse?"),
            ],
        )
        with patch.object(SlackOutboundAdapter, "_client", return_value=MagicMock(chat_postMessage=posted)):
            await adapter.deliver_paused(reply, {"channel": "C9"})

        blocks = posted.await_args.kwargs["blocks"]
        assert [b["block_id"] for b in blocks if b["type"] == "actions"] == [f"{BLOCK_PREFIX}call_a"]
        [notice] = [b for b in blocks if b["type"] == "context"]
        assert "call_q" in notice["elements"][0]["text"], "with buttons on screen, the question without them has to be named"


class TestPressParsing:
    """A press on a pause button, as the decision it carries."""

    def test_a_press_becomes_a_decision(self):
        request = _inbound()._decision_from_press(_press())

        [resume] = request.requests
        assert isinstance(resume, AgentResumeRequestAny)
        assert resume.run_id is None, "the runtime resolves the run from the interruption id"
        assert [(d.id, d.status) for d in resume.decisions] == [("call_9f2b", "approved")]
        assert request.session_id == "000.111", "the pause lives in the thread the turn opened"
        assert request.group_id == "C9"
        assert request.user_id == "U123", "who pressed is what lets a pre-hook decide whether they may"
        assert request.reply_context == {"channel": "C9", "thread_ts": "000.111", "user": "U123"}

    def test_a_press_is_identified_by_the_decision_not_the_click(self):
        """Slack mints action_ts per click, so a second press of one button must not be a new request."""
        first = _inbound()._decision_from_press(_press())
        again = _inbound()._decision_from_press(_press())
        denied = _inbound()._decision_from_press(_press(value="call_9f2b:denied"))

        assert first.request_id == again.request_id == "slack:C9:111.222:call_9f2b:approved"
        assert denied.request_id != first.request_id, "approve then deny are two decisions, not a repeat"

    def test_an_id_containing_a_colon_survives(self):
        request = _inbound()._decision_from_press(_press(value="ns:call_9f2b:denied"))

        assert [(d.id, d.status) for d in request.requests[0].decisions] == [("ns:call_9f2b", "denied")]

    @pytest.mark.parametrize("value", [None, "", "call_9f2b", "call_9f2b:nonsense", ":approved"])
    def test_a_press_that_does_not_parse_is_ignored(self, value):
        assert _inbound()._decision_from_press(_press(value=value)) is None

    def test_a_press_without_a_channel_is_ignored(self):
        press = _press()
        press["channel"] = {}
        assert _inbound()._decision_from_press(press) is None

    def test_an_unthreaded_pause_falls_back_to_the_message_timestamp(self):
        press = _press(thread_ts=None)
        press["container"] = {"message_ts": "111.222"}
        assert _inbound()._decision_from_press(press).session_id == "111.222"


class TestDenialReason:
    """Denying in Slack opens a modal, and the submitted reason rides the decision."""

    def test_the_deny_button_opens_a_modal_when_reasons_are_collected(self):
        adapter = _outbound()

        assert adapter._button("call_a", "denied")["action_id"] == f"{REASON_PREFIX}denied"
        assert adapter._button("call_a", "approved")["action_id"] == f"{ACTION_PREFIX}approved"

    def test_an_adapter_that_collects_no_reason_decides_from_the_press(self):
        adapter = _outbound()
        adapter.DENY_COLLECTS_REASON = False

        assert adapter._button("call_a", "denied")["action_id"] == f"{ACTION_PREFIX}denied"

    def test_the_modal_carries_the_whole_return_address(self):
        """A view_submission has no channel and no message of its own."""
        view = _inbound()._reason_modal(_press(value="call_9f2b:denied"))

        assert view["callback_id"] == MODAL_CALLBACK_ID
        assert json.loads(view["private_metadata"]) == {
            "value": "call_9f2b:denied",
            "channel": "C9",
            "ts": "111.222",
            "thread_ts": "000.111",
            "user": "U123",
        }
        [block] = view["blocks"]
        assert block["optional"] is True, "a denial must stay possible for someone with nothing to type"

    def test_a_submission_becomes_a_denial_carrying_its_reason(self):
        request = _inbound()._decision_from_modal(_submission("Customer was already refunded."))

        [resume] = request.requests
        [decision] = resume.decisions
        assert (decision.id, decision.status) == ("call_9f2b", "denied")
        assert decision.message == "Customer was already refunded."
        assert request.session_id == "000.111"
        assert request.request_id == "slack:C9:111.222:call_9f2b:denied"
        assert request.reply_context == {"channel": "C9", "thread_ts": "000.111", "user": "U123"}

    def test_a_submission_with_no_reason_still_denies(self):
        [decision] = _inbound()._decision_from_modal(_submission(None)).requests[0].decisions

        assert (decision.status, decision.message) == ("denied", None)

    def test_a_submission_and_a_press_share_one_request_id(self):
        """The same decision answered either way must deduplicate against itself."""
        pressed = _inbound()._decision_from_press(_press(value="call_9f2b:denied"))
        submitted = _inbound()._decision_from_modal(_submission("why"))

        assert pressed.request_id == submitted.request_id

    @pytest.mark.parametrize("metadata", ["", "not-json", '{"channel": "C9"}'])
    def test_a_submission_whose_metadata_does_not_parse_is_ignored(self, metadata):
        body = _submission("why")
        body["view"]["private_metadata"] = metadata

        assert _inbound()._decision_from_modal(body) is None
