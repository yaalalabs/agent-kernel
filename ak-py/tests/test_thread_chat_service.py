from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.chat_service import ChatService
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import AgentReplyText, AgentRequestAttachmentRef, BaseRunRequest, StreamChunk
from agentkernel.core.thread import ConversationThreadManager, ThreadNamingStrategy
from agentkernel.core.thread.store.in_memory import InMemoryThreadStore


class EchoNaming(ThreadNamingStrategy):
    """Offline test strategy: the first prompt becomes the name, no LLM call."""

    def generate_name(self, prompt: str) -> str:
        return (prompt or "").strip()


@pytest.fixture
def thread_enabled():
    """Enable thread support with the in-memory store for the duration of a test."""
    AKConfig.get().thread = _ThreadStoreConfig(type="memory")
    ConversationThreadManager.reset()
    ConversationThreadManager.set_naming_strategy(EchoNaming())
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


def _mock_handler(session: Session):
    """Build a mocked AgentHandler whose run returns a fixed reply."""
    handler = MagicMock()
    handler.run_sync.return_value = AgentReplyText(response="agent says hi")
    handler.get_response_session_id.side_effect = lambda sid: sid
    handler.service.session = session
    return handler


class TestChatServiceThreadIntegration:
    """Tests for the thread flow inside ChatService."""

    def test_thread_off_no_user_id_required(self):
        AKConfig.get().thread = None
        ConversationThreadManager.reset()
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            status, body = service.process_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))
        assert status == 200
        assert body["result"] == "agent says hi"

    def test_thread_on_missing_user_id_rejected(self, thread_enabled):
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            status, body = service.process_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))
        assert status == 400
        assert "user_id" in body["error"]
        handler.run_sync.assert_not_called()

    def test_thread_on_appends_user_and_assistant_messages(self, thread_enabled):
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            status, _ = service.process_chat_request(BaseRunRequest(prompt="hi there", session_id="s1", user_id="u1"))
        assert status == 200

        thread = thread_enabled.get_thread("s1")
        assert thread is not None
        assert thread.user_id == "u1"
        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role, m.content) for m in messages] == [("user", "hi there"), ("assistant", "agent says hi")]

    def test_thread_on_reuses_thread_across_requests(self, thread_enabled):
        service = ChatService()
        with patch("agentkernel.core.chat_service.AgentHandler", side_effect=lambda: _mock_handler(Session("s1"))):
            service.process_chat_request(BaseRunRequest(prompt="first", session_id="s1", user_id="u1"))
            service.process_chat_request(BaseRunRequest(prompt="second", session_id="s1", user_id="u1"))

        messages = thread_enabled.get_messages("s1", limit=200).messages
        assert len(messages) == 4
        assert messages[2].content == "second"

    def test_thread_on_group_and_name_applied_at_creation(self, thread_enabled):
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service.process_chat_request(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1", group_id="g1", thread_name="Support chat"))

        thread = thread_enabled.get_thread("s1")
        assert thread.group_id == "g1"
        assert thread.name == "Support chat"

    def test_thread_on_thread_name_renames_existing_thread(self, thread_enabled):
        service = ChatService()
        with patch("agentkernel.core.chat_service.AgentHandler", side_effect=lambda: _mock_handler(Session("s1"))):
            service.process_chat_request(BaseRunRequest(prompt="first prompt", session_id="s1", user_id="u1"))
            assert thread_enabled.get_thread("s1").name == "first prompt"  # auto-named, unlocked
            assert thread_enabled.get_thread("s1").name_locked is False

            service.process_chat_request(BaseRunRequest(prompt="second", session_id="s1", user_id="u1", thread_name="Renamed via chat"))

        thread = thread_enabled.get_thread("s1")
        assert thread.name == "Renamed via chat"
        assert thread.name_locked is True

    def test_thread_on_failed_run_appends_no_assistant_message(self, thread_enabled):
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_sync.side_effect = RuntimeError("agent blew up")
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            status, _ = service.process_chat_request(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1"))
        assert status == 500

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role,) for m in messages] == [("user",)]

    def test_thread_on_multimodal_off_attachment_rejected(self, thread_enabled):
        original = AKConfig.get().multimodal.enabled
        AKConfig.get().multimodal.enabled = False
        try:
            service = ChatService()
            handler = _mock_handler(Session("s1"))
            request = BaseRunRequest(
                prompt="what animal is this?",
                session_id="s1",
                user_id="u1",
                images=[{"image_data": "Zm9v", "name": "a.png", "mime_type": "image/png"}],
            )
            with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
                status, body = service.process_chat_request(request)
            assert status == 400
            assert "multimodal" in body["error"]
            handler.run_sync.assert_not_called()
            # The rejection fires before any thread state exists — no phantom thread
            assert thread_enabled.get_thread("s1") is None
        finally:
            AKConfig.get().multimodal.enabled = original

    def test_thread_on_session_cache_rejected_creates_no_thread(self, thread_enabled):
        original_enabled = AKConfig.get().multimodal.enabled
        original_storage = AKConfig.get().multimodal.storage_type
        AKConfig.get().multimodal.enabled = True
        AKConfig.get().multimodal.storage_type = "session_cache"
        try:
            service = ChatService()
            handler = _mock_handler(Session("s1"))
            with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
                status, body = service.process_chat_request(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1"))
            assert status == 400
            assert "session_cache" in body["error"]
            assert thread_enabled.get_thread("s1") is None
        finally:
            AKConfig.get().multimodal.enabled = original_enabled
            AKConfig.get().multimodal.storage_type = original_storage

    def test_stream_thread_on_missing_user_id_rejected(self, thread_enabled):
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            with pytest.raises(ValueError, match="user_id"):
                service.process_stream_chat_sync(BaseRunRequest(prompt="hi", session_id="s1"))
        handler.run_stream_sync.assert_not_called()

    def test_stream_thread_on_appends_user_and_accumulated_assistant(self, thread_enabled):
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_stream_sync.return_value = iter([StreamChunk(delta="Hel"), StreamChunk(delta="lo!"), StreamChunk(done=True)])
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            gen = service.process_stream_chat_sync(BaseRunRequest(prompt="hi there", session_id="s1", user_id="u1"))
            list(gen)  # drain the stream

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role, m.content) for m in messages] == [("user", "hi there"), ("assistant", "Hello!")]

    def test_stream_thread_on_failed_stream_appends_no_assistant_message(self, thread_enabled):
        def _failing_stream(requests):
            yield StreamChunk(delta="par")
            raise RuntimeError("stream blew up")

        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_stream_sync.side_effect = _failing_stream
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            gen = service.process_stream_chat_sync(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1"))
            list(gen)  # drain — the error is yielded as an error chunk

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role,) for m in messages] == [("user",)]

    def test_stream_thread_on_halted_stream_appends_no_assistant_message(self, thread_enabled):
        # A pre-hook halt (e.g. input guardrail) yields an error chunk without raising —
        # the thread must not record a blank assistant message.
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_stream_sync.return_value = iter([StreamChunk(error="blocked by guardrail", done=True)])
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            gen = service.process_stream_chat_sync(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1"))
            list(gen)  # drain the stream

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role,) for m in messages] == [("user",)]

    def test_stream_thread_on_empty_stream_appends_no_assistant_message(self, thread_enabled):
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_stream_sync.return_value = iter([StreamChunk(done=True)])
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            gen = service.process_stream_chat_sync(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1"))
            list(gen)  # drain the stream

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role,) for m in messages] == [("user",)]

    @pytest.mark.asyncio
    async def test_stream_async_thread_on_halted_stream_appends_no_assistant_message(self, thread_enabled):
        async def _achunks(requests):
            yield StreamChunk(error="blocked by guardrail", done=True)

        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_stream_async.side_effect = _achunks
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            gen = await service.process_stream_chat_async(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1"))
            async for _ in gen:
                pass

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role,) for m in messages] == [("user",)]

    @pytest.mark.asyncio
    async def test_stream_async_thread_on_appends_user_and_accumulated_assistant(self, thread_enabled):
        async def _achunks(requests):
            for chunk in [StreamChunk(delta="Hi "), StreamChunk(delta="Bob"), StreamChunk(done=True)]:
                yield chunk

        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_stream_async.side_effect = _achunks
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            gen = await service.process_stream_chat_async(BaseRunRequest(prompt="hey", session_id="s1", user_id="u1"))
            async for _ in gen:
                pass

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role, m.content) for m in messages] == [("user", "hey"), ("assistant", "Hi Bob")]

    def test_stream_thread_off_no_thread_calls(self):
        AKConfig.get().thread = None
        ConversationThreadManager.reset()
        service = ChatService()
        handler = _mock_handler(Session("s1"))
        handler.run_stream_sync.return_value = iter([StreamChunk(delta="ok", done=True)])
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            gen = service.process_stream_chat_sync(BaseRunRequest(prompt="hi", session_id="s1"))
            chunks = list(gen)
        assert chunks  # streamed fine without user_id when thread support is off

    def test_thread_on_attachment_passed_in_band_as_ref(self, thread_enabled):
        original_enabled = AKConfig.get().multimodal.enabled
        original_storage = AKConfig.get().multimodal.storage_type
        AKConfig.get().multimodal.enabled = True
        AKConfig.get().multimodal.storage_type = "in_memory"
        try:
            session = Session("s1")
            service = ChatService()
            handler = _mock_handler(session)
            request = BaseRunRequest(
                prompt="describe this",
                session_id="s1",
                user_id="u1",
                images=[{"image_data": "aW1n", "name": "pic.png", "mime_type": "image/png"}],
            )
            with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
                status, _ = service.process_chat_request(request)
            assert status == 200

            # The request list handed to the runner carries the id in-band as an
            # AgentRequestAttachmentRef (no raw image), matching the stored thread ref.
            passed_requests = handler.run_sync.call_args.args[0]
            refs = [r for r in passed_requests if isinstance(r, AgentRequestAttachmentRef)]
            assert len(refs) == 1

            messages = thread_enabled.get_messages("s1").messages
            assert messages[0].attachments[0].attachment_id == refs[0].attachment_id
        finally:
            AKConfig.get().multimodal.enabled = original_enabled
            AKConfig.get().multimodal.storage_type = original_storage
