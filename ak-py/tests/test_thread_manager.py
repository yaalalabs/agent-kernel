from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agentkernel.core.config import AKConfig, _ThreadNamingConfig, _ThreadStoreConfig
from agentkernel.core.model import AgentRequestAttachmentRef, AgentRequestFile, AgentRequestImage, AgentRequestText
from agentkernel.integration.thread import ConversationThreadManager, ThreadNamingStrategy
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore


class EchoNaming(ThreadNamingStrategy):
    """Offline test strategy: the first prompt becomes the name, no LLM call."""

    def generate_name(self, prompt: str) -> str:
        return (prompt or "").strip()


@pytest.fixture
def thread_enabled():
    """Enable thread support with the in-memory store for the duration of a test.

    An offline naming stub is registered so no test ever reaches LiteLLM; the
    LLM naming tests drop the stub and mock the LiteLLM call instead.
    """
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
    ConversationThreadManager.reset()
    ConversationThreadManager.set_naming_strategy(EchoNaming())
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


@pytest.fixture
def thread_enabled_llm(thread_enabled):
    """Rebuild the manager with the real default (LLM) naming strategy."""
    ConversationThreadManager.reset()  # drops the offline stub
    yield ConversationThreadManager.get()


def _llm_response(content):
    """Build a minimal litellm.completion response carrying the given content."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


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

        # Second call: user_id/group_id are fixed at creation; only an explicit name applies
        loaded = thread_enabled.get_or_create_thread("s1", "u2", group_id="g2", name="other")
        assert loaded.user_id == "u1"
        assert loaded.group_id == "g1"
        assert loaded.name == "other"
        assert loaded.name_locked is True

    def test_explicit_name_wins_over_prompt(self, thread_enabled):
        thread = thread_enabled.get_or_create_thread("s1", "u1", name="My thread", first_prompt="Hello world")
        assert thread.name == "My thread"

    def test_name_falls_back_to_prompt_when_absent(self, thread_enabled):
        thread = thread_enabled.get_or_create_thread("s1", "u1", first_prompt="What is the refund policy?")
        assert thread.name == "What is the refund policy?"  # from the naming strategy

    def test_provided_name_locks_thread_name(self, thread_enabled):
        thread = thread_enabled.get_or_create_thread("s1", "u1", name="My thread", first_prompt="Hello")
        assert thread.name_locked is True

    def test_auto_generated_name_is_not_locked(self, thread_enabled):
        thread = thread_enabled.get_or_create_thread("s1", "u1", first_prompt="Hello")
        assert thread.name_locked is False

    def test_custom_naming_strategy_overrides_default(self, thread_enabled):
        class UpperNaming(ThreadNamingStrategy):
            def generate_name(self, prompt: str) -> str:
                return prompt.upper()

        ConversationThreadManager.set_naming_strategy(UpperNaming())
        thread = thread_enabled.get_or_create_thread("s1", "u1", first_prompt="hello")
        assert thread.name == "HELLO"

    def test_custom_naming_strategy_not_used_for_explicit_name(self, thread_enabled):
        class UpperNaming(ThreadNamingStrategy):
            def generate_name(self, prompt: str) -> str:
                return prompt.upper()

        ConversationThreadManager.set_naming_strategy(UpperNaming())
        thread = thread_enabled.get_or_create_thread("s1", "u1", name="My thread", first_prompt="hello")
        assert thread.name == "My thread"

    def test_name_on_existing_thread_renames_and_locks(self, thread_enabled):
        created = thread_enabled.get_or_create_thread("s1", "u1", first_prompt="Hello world")
        assert created.name_locked is False
        renamed = thread_enabled.get_or_create_thread("s1", "u1", name="Better name")
        assert renamed.name == "Better name"
        assert renamed.name_locked is True
        assert thread_enabled.get_thread("s1").name == "Better name"

    def test_name_on_existing_thread_renames_even_when_locked(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", name="First name", first_prompt="Hello")
        renamed = thread_enabled.get_or_create_thread("s1", "u1", name="Second name")
        assert renamed.name == "Second name"
        assert renamed.name_locked is True

    def test_same_name_resent_skips_store_write(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", name="My thread", first_prompt="Hello")
        with patch.object(thread_enabled._store, "update_name") as update_name:
            thread = thread_enabled.get_or_create_thread("s1", "u1", name="My thread")
        assert thread.name == "My thread"
        update_name.assert_not_called()

    def test_blank_name_is_ignored(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="Hello")
        thread = thread_enabled.get_or_create_thread("s1", "u1", name="   ")
        assert thread.name == "Hello"
        assert thread.name_locked is False

    def test_blank_name_at_creation_does_not_lock(self, thread_enabled):
        thread = thread_enabled.get_or_create_thread("s1", "u1", name="  ", first_prompt="Hello")
        assert thread.name == "Hello"  # naming strategy applies
        assert thread.name_locked is False

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

    def test_store_attachments_disabled_multimodal_rejects_attachments(self, thread_enabled):
        original = AKConfig.get().multimodal.enabled
        AKConfig.get().multimodal.enabled = False
        try:
            requests = [AgentRequestImage(image_data="Zm9v", name="a.png", mime_type="image/png")]
            with pytest.raises(ValueError, match="multimodal"):
                thread_enabled.store_attachments("s1", requests)
        finally:
            AKConfig.get().multimodal.enabled = original

    def test_store_attachments_disabled_multimodal_text_passes_through(self, thread_enabled):
        original = AKConfig.get().multimodal.enabled
        AKConfig.get().multimodal.enabled = False
        try:
            requests = [AgentRequestText(prompt="just text")]
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
                thread_enabled.store_attachments("s1", [AgentRequestText(prompt="hi")])
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
                AgentRequestText(prompt="look at these"),
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


class TestLLMThreadNaming:
    """Tests for the default LLM-based ThreadNamingStrategy with a mocked LiteLLM call."""

    def test_llm_name_used_and_unlocked(self, thread_enabled_llm):
        with patch("litellm.completion", return_value=_llm_response("Paris Trip Planning")) as completion:
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="Help me plan a trip to Paris")
        assert thread.name == "Paris Trip Planning"
        assert thread.name_locked is False
        completion.assert_called_once()
        assert completion.call_args.kwargs["model"] == "gpt-4o-mini"

    def test_llm_naming_model_config_honored(self, thread_enabled_llm):
        AKConfig.get().thread.naming.model = "gpt-4o"
        with patch("litellm.completion", return_value=_llm_response("Title")) as completion:
            thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="Hello there")
        assert completion.call_args.kwargs["model"] == "gpt-4o"

    def test_llm_name_surrounding_quotes_stripped(self, thread_enabled_llm):
        with patch("litellm.completion", return_value=_llm_response('  "Paris Trip"  ')):
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="Trip to Paris")
        assert thread.name == "Paris Trip"

    def test_llm_name_capped_at_max_length(self, thread_enabled_llm):
        with patch("litellm.completion", return_value=_llm_response("title " * 30)):
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="Hello there")
        assert len(thread.name) <= 81  # 80 chars + ellipsis
        assert thread.name.endswith("…")

    def test_llm_failure_falls_back_to_truncation(self, thread_enabled_llm):
        with patch("litellm.completion", side_effect=Exception("no API key")):
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="What is the refund policy?")
        assert thread.name == "What is the refund policy?"
        assert thread.name_locked is False

    def test_llm_failure_fallback_trims_long_prompt_at_word_boundary(self, thread_enabled_llm):
        prompt = "word " * 40  # far beyond 80 chars
        with patch("litellm.completion", side_effect=Exception("no API key")):
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt=prompt)
        assert len(thread.name) <= 81  # 80 chars + ellipsis
        assert thread.name.endswith("…")
        assert not thread.name[:-1].endswith(" ")

    def test_naming_max_length_config_honored(self, thread_enabled_llm):
        AKConfig.get().thread.naming.max_length = 10
        with patch("litellm.completion", return_value=_llm_response("hello wonderful world")):
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="Tell me something nice")
        assert thread.name == "hello…"

    def test_llm_empty_reply_falls_back_to_truncation(self, thread_enabled_llm):
        with patch("litellm.completion", return_value=_llm_response("")):
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="What is the refund policy?")
        assert thread.name == "What is the refund policy?"

    def test_llm_blank_prompt_skips_call(self, thread_enabled_llm):
        with patch("litellm.completion") as completion:
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="   ")
        assert thread.name == ""
        completion.assert_not_called()

    def test_llm_explicit_name_skips_call(self, thread_enabled_llm):
        with patch("litellm.completion") as completion:
            thread = thread_enabled_llm.get_or_create_thread("s1", "u1", name="My thread", first_prompt="Hello")
        assert thread.name == "My thread"
        assert thread.name_locked is True
        completion.assert_not_called()

    def test_build_instruction_includes_prompt_and_gibberish_rule(self):
        instruction = ThreadNamingStrategy().build_instruction("Plan my Paris trip")
        assert "Plan my Paris trip" in instruction
        assert "New conversation" in instruction

    def test_custom_instruction_subclass_honored(self, thread_enabled_llm):
        class MyNaming(ThreadNamingStrategy):
            def build_instruction(self, prompt: str) -> str:
                return f"CUSTOM: {prompt}"

        ConversationThreadManager.set_naming_strategy(MyNaming())
        with patch("litellm.completion", return_value=_llm_response("Title")) as completion:
            thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="Hello")
        assert completion.call_args.kwargs["messages"] == [{"role": "user", "content": "CUSTOM: Hello"}]

    def test_naming_config_defaults(self):
        config = _ThreadNamingConfig()
        assert config.model == "gpt-4o-mini"
        assert config.max_length == 80

    def test_missing_litellm_warns_at_construction(self, caplog):
        with patch("importlib.util.find_spec", return_value=None):
            with caplog.at_level("WARNING", logger="ak.thread.naming"):
                ThreadNamingStrategy()
        assert "agentkernel[thread]" in caplog.text

    def test_custom_generate_name_subclass_does_not_warn_at_construction(self, caplog):
        with patch("importlib.util.find_spec", return_value=None):
            with caplog.at_level("WARNING", logger="ak.thread.naming"):
                EchoNaming()  # overrides generate_name — never makes the LLM call
        assert caplog.text == ""

    def test_litellm_import_error_falls_back_with_install_hint(self, thread_enabled_llm, caplog):
        with patch.object(ThreadNamingStrategy, "_complete", side_effect=ImportError("No module named 'litellm'")):
            with caplog.at_level("WARNING", logger="ak.thread.naming"):
                thread = thread_enabled_llm.get_or_create_thread("s1", "u1", first_prompt="What is the refund policy?")
        assert thread.name == "What is the refund policy?"  # truncation fallback
        assert "agentkernel[thread]" in caplog.text
