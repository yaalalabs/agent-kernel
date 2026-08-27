"""
Attachment source forms through ConversationThreadManager.store_attachments.

The direct path already classifies an attachment's source form before deciding what to do with it
(see test_multimodal_source_forms.py). The thread path did not: it stored whatever the data field
held as though it were base64, so a URL was saved as if the URL text were the image bytes.

The consequence was worse than the storage being wrong, and `test_url_image_survives_to_the_agent`
is the guard for it: the request that replaces a stored attachment is an AgentRequestAttachmentRef,
and MultimodalPreHook always strips a ref before the agent runs. A URL therefore reached the agent
as nothing at all — while the identical request with threads off reached it intact.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import AgentRequestAttachmentRef, AgentRequestFile, AgentRequestImage, AgentRequestText
from agentkernel.core.multimodal.hooks import MultimodalPreHook
from agentkernel.core.multimodal.storage import AttachmentStorageManager
from agentkernel.core.multimodal.storage.in_memory import InMemoryAttachmentStore
from agentkernel.integration.thread import ConversationThreadManager, ThreadNamingStrategy
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore

REMOTE_SOURCES = ["http://example.com/cat.png", "https://example.com/cat.png", "s3://bucket/cat.png"]


class EchoNaming(ThreadNamingStrategy):
    """Offline test strategy: the first prompt becomes the name, no LLM call."""

    def generate_name(self, prompt: str) -> str:
        return (prompt or "").strip()


@pytest.fixture
def thread_and_multimodal():
    """Thread support and in-memory multimodal storage, both enabled for one test."""
    original_enabled = AKConfig.get().multimodal.enabled
    original_storage = AKConfig.get().multimodal.storage_type
    AKConfig.get().multimodal.enabled = True
    AKConfig.get().multimodal.storage_type = "in_memory"
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
    ConversationThreadManager.reset()
    ConversationThreadManager.set_naming_strategy(EchoNaming())
    InMemoryAttachmentStore._attachments.clear()
    InMemoryAttachmentStore._index.clear()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().multimodal.enabled = original_enabled
    AKConfig.get().multimodal.storage_type = original_storage
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryAttachmentStore._attachments.clear()
    InMemoryAttachmentStore._index.clear()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


def _record(session_id: str, attachment_id: str):
    """The attachment store's record for an id."""
    return AttachmentStorageManager(session_id=session_id).get_attachment_data([attachment_id])[0]


def _run_hook(session: Session, requests):
    hook = MultimodalPreHook()
    with patch.object(hook, "_describe_attachment_briefly", new=AsyncMock(return_value="a small test image")):
        return asyncio.run(hook.on_run(session, agent=None, requests=requests))


class TestStoredSourceForms:
    """Source forms whose bytes the thread store can hold."""

    def test_bare_base64_is_stored_as_before(self, thread_and_multimodal):
        requests = [AgentRequestImage(image_data="aW1n", name="pic.png", mime_type="image/png")]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert isinstance(rebuilt[0], AgentRequestAttachmentRef)
        assert refs[0].attachment_id == rebuilt[0].attachment_id
        record = _record("s1", refs[0].attachment_id)
        assert record.data == "aW1n"
        assert record.url is None

    def test_data_uri_stores_the_payload_without_its_header(self, thread_and_multimodal):
        requests = [AgentRequestImage(image_data="data:image/png;base64,aW1n", name="pic.png", mime_type="image/png")]
        _, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert _record("s1", refs[0].attachment_id).data == "aW1n"

    def test_data_uri_mime_type_beats_the_requests_declared_one(self, thread_and_multimodal):
        requests = [AgentRequestImage(image_data="data:image/png;base64,aW1n", name="pic", mime_type="image/jpeg")]
        _, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert refs[0].mime_type == "image/png"

    def test_file_default_mime_applies_when_nothing_declares_one(self, thread_and_multimodal):
        requests = [AgentRequestFile(file_data="ZmlsZQ==", name="doc.bin", mime_type=None)]
        _, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert refs[0].mime_type == "application/octet-stream"


class TestRemoteSourceForms:
    """Source forms the thread store must decline, leaving them for the adapter."""

    @pytest.mark.parametrize("source", REMOTE_SOURCES)
    def test_remote_image_travels_on_untouched(self, thread_and_multimodal, source):
        requests = [AgentRequestImage(image_data=source, name="cat.png", mime_type="image/png")]
        rebuilt, _ = thread_and_multimodal.store_attachments("s1", requests)

        assert rebuilt[0] is requests[0]

    @pytest.mark.parametrize("source", REMOTE_SOURCES)
    def test_remote_image_is_recorded_by_url_with_no_bytes(self, thread_and_multimodal, source):
        requests = [AgentRequestImage(image_data=source, name="cat.png", mime_type="image/png")]
        _, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert len(refs) == 1
        assert refs[0].name == "cat.png"
        assert refs[0].mime_type == "image/png"

        record = _record("s1", refs[0].attachment_id)
        assert record.url == source
        assert record.data == ""

    def test_remote_file_is_recorded_by_url_and_travels_on(self, thread_and_multimodal):
        source = "https://example.com/doc.pdf"
        requests = [AgentRequestFile(file_data=source, name="doc.pdf", mime_type="application/pdf")]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert rebuilt[0] is requests[0]
        assert _record("s1", refs[0].attachment_id).url == source

    def test_non_base64_data_uri_is_recorded_like_a_url(self, thread_and_multimodal):
        source = "data:text/plain,hello%20world"
        requests = [AgentRequestFile(file_data=source, name="note.txt", mime_type="text/plain")]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert rebuilt[0] is requests[0]
        record = _record("s1", refs[0].attachment_id)
        assert record.url == source
        assert record.data == ""

    def test_remote_reference_is_recognised_whatever_the_scheme_case(self, thread_and_multimodal):
        source = "HTTPS://EXAMPLE.COM/CAT.PNG"
        requests = [AgentRequestImage(image_data=source, name="cat.png", mime_type="image/png")]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert rebuilt[0] is requests[0]
        assert _record("s1", refs[0].attachment_id).url == source


class TestMixedAndEdgeCases:
    """Several attachments in one turn, and sources carrying nothing at all."""

    def test_mixed_forms_keep_their_order_in_both_lists(self, thread_and_multimodal):
        requests = [
            AgentRequestText(prompt="look at these"),
            AgentRequestImage(image_data="aW1n", name="stored.png", mime_type="image/png"),
            AgentRequestImage(image_data="https://example.com/remote.png", name="remote.png", mime_type="image/png"),
            AgentRequestFile(file_data="ZmlsZQ==", name="doc.pdf", mime_type="application/pdf"),
        ]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert isinstance(rebuilt[0], AgentRequestText)
        assert isinstance(rebuilt[1], AgentRequestAttachmentRef)
        assert rebuilt[2] is requests[2]
        assert isinstance(rebuilt[3], AgentRequestAttachmentRef)

        assert [r.name for r in refs] == ["stored.png", "remote.png", "doc.pdf"]
        assert [_record("s1", r.attachment_id).url for r in refs] == [None, "https://example.com/remote.png", None]

    def test_several_remote_images_are_each_recorded(self, thread_and_multimodal):
        requests = [AgentRequestImage(image_data=source, name=f"{i}.png", mime_type="image/png") for i, source in enumerate(REMOTE_SOURCES)]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert [_record("s1", r.attachment_id).url for r in refs] == REMOTE_SOURCES
        assert len({r.attachment_id for r in refs}) == 3
        assert rebuilt == requests

    def test_attachment_with_no_data_is_neither_stored_nor_recorded(self, thread_and_multimodal):
        requests = [AgentRequestText(prompt="hi"), AgentRequestImage(image_data="", name="empty.png", mime_type="image/png")]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert refs == []
        assert rebuilt == requests

    def test_data_uri_with_an_empty_payload_is_dropped_like_no_data(self, thread_and_multimodal):
        requests = [AgentRequestImage(image_data="data:image/png;base64,", name="empty.png", mime_type="image/png")]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)

        assert refs == []
        assert rebuilt[0] is requests[0]
        assert InMemoryAttachmentStore._attachments == {}


class TestEndToEndThroughTheHook:
    """The regression the unit tests above cannot catch: what the agent actually receives."""

    def test_url_image_survives_to_the_agent(self, thread_and_multimodal):
        requests = [
            AgentRequestText(prompt="what is this?"),
            AgentRequestImage(image_data="https://example.com/cat.png", name="cat.png", mime_type="image/png"),
        ]
        rebuilt, _ = thread_and_multimodal.store_attachments("s1", requests)
        result = _run_hook(Session("s1"), rebuilt)

        remote = [r for r in result if isinstance(r, AgentRequestImage)]
        assert len(remote) == 1
        assert remote[0].image_data == "https://example.com/cat.png"

    def test_stored_image_is_still_described_and_stripped(self, thread_and_multimodal):
        requests = [
            AgentRequestText(prompt="what is this?"),
            AgentRequestImage(image_data="aW1n", name="pic.png", mime_type="image/png"),
        ]
        rebuilt, refs = thread_and_multimodal.store_attachments("s1", requests)
        result = _run_hook(Session("s1"), rebuilt)

        assert len(result) == 1
        assert refs[0].attachment_id in result[0].prompt
        assert "a small test image" in result[0].prompt
