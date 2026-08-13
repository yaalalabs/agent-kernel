import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentRequestAttachmentRef, AgentRequestImage, AgentRequestText
from agentkernel.core.multimodal.hooks import MultimodalPreHook
from agentkernel.core.multimodal.storage import AttachmentStorageManager
from agentkernel.core.multimodal.storage.in_memory import InMemoryAttachmentStore


@pytest.fixture
def multimodal_enabled():
    """Enable in-memory multimodal storage for the duration of a test."""
    original_enabled = AKConfig.get().multimodal.enabled
    original_storage = AKConfig.get().multimodal.storage_type
    AKConfig.get().multimodal.enabled = True
    AKConfig.get().multimodal.storage_type = "in_memory"
    InMemoryAttachmentStore._attachments.clear()
    InMemoryAttachmentStore._index.clear()
    yield
    AKConfig.get().multimodal.enabled = original_enabled
    AKConfig.get().multimodal.storage_type = original_storage
    InMemoryAttachmentStore._attachments.clear()
    InMemoryAttachmentStore._index.clear()


def _run_hook(session: Session, requests):
    hook = MultimodalPreHook()
    with patch.object(hook, "_describe_attachment_briefly", new=AsyncMock(return_value="a small test image")):
        return asyncio.run(hook.on_run(session, agent=None, requests=requests))


class TestMultimodalPreHookThreadMode:
    """Tests for the in-band AgentRequestAttachmentRef handling in MultimodalPreHook."""

    def test_thread_mode_resolves_ref_by_id_and_skips_save(self, multimodal_enabled):
        # Pre-store the attachment as ChatService would have, then reference it by id.
        pre_id = AttachmentStorageManager(session_id="s1").save_attachment(
            data="aW1n", attachment_type="image", name="pic.png", mime_type="image/png"
        )
        count_before = len(InMemoryAttachmentStore._attachments)

        session = Session("s1")
        requests = [
            AgentRequestText(prompt="what is this?"),
            AgentRequestAttachmentRef(attachment_id=pre_id),
        ]

        result = _run_hook(session, requests)

        # Binary stripped, description injected referencing the pre-stored id
        assert len(result) == 1
        assert pre_id in result[0].prompt
        assert "a small test image" in result[0].prompt
        # The hook did not save a new attachment — count unchanged
        assert len(InMemoryAttachmentStore._attachments) == count_before

    def test_thread_mode_missing_ref_is_skipped(self, multimodal_enabled):
        session = Session("s1")
        requests = [
            AgentRequestText(prompt="what is this?"),
            AgentRequestAttachmentRef(attachment_id="does-not-exist"),
        ]
        result = _run_hook(session, requests)
        # No attachment resolved → no description injected, original text preserved
        assert len(result) == 1
        assert result[0].prompt == "what is this?"

    def test_thread_off_saves_raw_image_normally(self, multimodal_enabled):
        session = Session("s1")
        requests = [
            AgentRequestText(prompt="what is this?"),
            AgentRequestImage(image_data="aW1n", name="pic.png", mime_type="image/png"),
        ]

        result = _run_hook(session, requests)

        assert len(result) == 1
        assert "a small test image" in result[0].prompt
        # The hook saved the attachment itself
        assert len(InMemoryAttachmentStore._attachments) == 1
