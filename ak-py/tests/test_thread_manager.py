import pytest

from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import AgentRequestAttachmentRef, AgentRequestFile, AgentRequestImage, AgentRequestText
from agentkernel.core.thread import ConversationThreadManager
from agentkernel.core.thread.store.in_memory import InMemoryThreadStore


@pytest.fixture
def thread_enabled():
    """Enable thread support with the in-memory store for the duration of a test."""
    AKConfig.get().thread = _ThreadStoreConfig(type="memory")
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


class TestConversationThreadManager:
    """Tests for ConversationThreadManager."""

    def test_get_returns_none_when_disabled(self):
        AKConfig.get().thread = None
        ConversationThreadManager.reset()
        assert ConversationThreadManager.get() is None

    def test_get_returns_shared_instance_when_enabled(self, thread_enabled):
        assert thread_enabled is not None
        assert ConversationThreadManager.get() is thread_enabled

    def test_get_or_create_creates_then_loads(self, thread_enabled):
        created = thread_enabled.get_or_create_thread("s1", "u1", group_id="g1", first_prompt="Hello")
        assert created.user_id == "u1"
        assert created.group_id == "g1"

        # Second call with different metadata returns the existing thread untouched
        loaded = thread_enabled.get_or_create_thread("s1", "u2", group_id="g2", name="other")
        assert loaded.user_id == "u1"
        assert loaded.group_id == "g1"

    def test_explicit_name_wins_over_prompt(self, thread_enabled):
        thread = thread_enabled.get_or_create_thread("s1", "u1", name="My thread", first_prompt="Hello world")
        assert thread.name == "My thread"

    def test_name_falls_back_to_prompt_prefix(self, thread_enabled):
        thread = thread_enabled.get_or_create_thread("s1", "u1", first_prompt="What is the refund policy?")
        assert thread.name == "What is the refund policy?"

    def test_long_prompt_name_is_trimmed_at_word_boundary(self, thread_enabled):
        prompt = "word " * 40  # far beyond 80 chars
        thread = thread_enabled.get_or_create_thread("s1", "u1", first_prompt=prompt)
        assert len(thread.name) <= 81  # 80 chars + ellipsis
        assert thread.name.endswith("…")
        assert not thread.name[:-1].endswith(" ")

    def test_append_message_ordering(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="hi")
        thread_enabled.append_message("s1", "user", "hi")
        thread_enabled.append_message("s1", "assistant", "hello!")

        page = thread_enabled.get_messages("s1")
        assert [(m.role, m.content) for m in page.messages] == [("user", "hi"), ("assistant", "hello!")]
        assert page.next_cursor is None

    def test_get_messages_pagination_with_cursor(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="hi")
        for i in range(5):
            thread_enabled.append_message("s1", "user", f"m{i}")

        page1 = thread_enabled.get_messages("s1", limit=2)
        assert [m.content for m in page1.messages] == ["m0", "m1"]
        assert page1.next_cursor is not None

        page2 = thread_enabled.get_messages("s1", limit=2, cursor=page1.next_cursor)
        assert [m.content for m in page2.messages] == ["m2", "m3"]

        page3 = thread_enabled.get_messages("s1", limit=2, cursor=page2.next_cursor)
        assert [m.content for m in page3.messages] == ["m4"]
        assert page3.next_cursor is None

    def test_get_messages_invalid_cursor_raises(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="hi")
        with pytest.raises(ValueError):
            thread_enabled.get_messages("s1", cursor="not-a-valid-cursor!!")

    def test_get_thread_returns_metadata_only(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="hi")
        thread_enabled.append_message("s1", "user", "hi")
        thread = thread_enabled.get_thread("s1")
        assert thread.messages == []

    def test_get_thread_ownership_enforced(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="hi")
        assert thread_enabled.get_thread("s1", user_id="u1") is not None
        with pytest.raises(PermissionError):
            thread_enabled.get_thread("s1", user_id="intruder")

    def test_get_thread_missing_returns_none(self, thread_enabled):
        assert thread_enabled.get_thread("missing") is None

    def test_list_threads(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.get_or_create_thread("s2", "u1", group_id="g1", first_prompt="b")
        thread_enabled.get_or_create_thread("s3", "u2", first_prompt="c")

        assert {t.session_id for t in thread_enabled.list_threads(user_id="u1").threads} == {"s1", "s2"}
        assert [t.session_id for t in thread_enabled.list_threads(group_id="g1").threads] == ["s2"]

    def test_store_attachments_disabled_multimodal_returns_unchanged(self, thread_enabled):
        original = AKConfig.get().multimodal.enabled
        AKConfig.get().multimodal.enabled = False
        try:
            requests = [AgentRequestImage(image_data="Zm9v", name="a.png", mime_type="image/png")]
            rebuilt, refs = thread_enabled.store_attachments("s1", requests)
            assert refs == []
            assert rebuilt is requests  # unchanged, same list
        finally:
            AKConfig.get().multimodal.enabled = original

    def test_store_attachments_session_cache_storage_rejected(self, thread_enabled):
        original_enabled = AKConfig.get().multimodal.enabled
        original_storage = AKConfig.get().multimodal.storage_type
        AKConfig.get().multimodal.enabled = True
        AKConfig.get().multimodal.storage_type = "session_cache"
        try:
            with pytest.raises(ValueError, match="session_cache"):
                thread_enabled.store_attachments("s1", [AgentRequestText(text="hi")])
        finally:
            AKConfig.get().multimodal.enabled = original_enabled
            AKConfig.get().multimodal.storage_type = original_storage

    def test_store_attachments_replaces_raw_with_ref_and_saves_bytes(self, thread_enabled):
        original_enabled = AKConfig.get().multimodal.enabled
        original_storage = AKConfig.get().multimodal.storage_type
        AKConfig.get().multimodal.enabled = True
        AKConfig.get().multimodal.storage_type = "in_memory"
        try:
            requests = [
                AgentRequestText(text="look at these"),
                AgentRequestImage(image_data="aW1n", name="pic.png", mime_type="image/png"),
                AgentRequestFile(file_data="ZmlsZQ==", name="doc.pdf", mime_type="application/pdf"),
            ]
            rebuilt, refs = thread_enabled.store_attachments("s1", requests)

            assert len(refs) == 2
            assert refs[0].name == "pic.png"
            assert refs[1].name == "doc.pdf"

            # The rebuilt list keeps the text and replaces each image/file with an
            # in-band AgentRequestAttachmentRef carrying the saved id, in order.
            assert isinstance(rebuilt[0], AgentRequestText)
            assert isinstance(rebuilt[1], AgentRequestAttachmentRef)
            assert isinstance(rebuilt[2], AgentRequestAttachmentRef)
            assert [r.attachment_id for r in rebuilt[1:]] == [refs[0].attachment_id, refs[1].attachment_id]
            # No raw image/file bytes remain in the rebuilt list
            assert not any(isinstance(r, (AgentRequestImage, AgentRequestFile)) for r in rebuilt)

            # Bytes are retrievable from the existing AttachmentStore by the saved ids
            from agentkernel.core.multimodal.storage import AttachmentStorageManager

            stored = AttachmentStorageManager(session_id="s1").get_attachment_data([r.attachment_id for r in refs])
            assert [a.data for a in stored] == ["aW1n", "ZmlsZQ=="]
        finally:
            AKConfig.get().multimodal.enabled = original_enabled
            AKConfig.get().multimodal.storage_type = original_storage
