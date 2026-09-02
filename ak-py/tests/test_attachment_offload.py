"""offload_attachments: moving attachment bytes into the store before a request travels."""

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentRequestAny, AgentRequestAttachmentRef, AgentRequestFile, AgentRequestImage, AgentRequestText
from agentkernel.core.multimodal.storage.offload import has_attachments, offload_attachments

DISABLED = "attachments need multimodal"
SESSION_CACHE = "session_cache cannot be read from another process"


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    yield
    AKConfig._reset()


@pytest.fixture
def multimodal(monkeypatch):
    monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
    monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "in_memory")
    AKConfig._reset()


def _offload(requests):
    return offload_attachments("s1", requests, attachments_disabled_error=DISABLED, session_cache_error=SESSION_CACHE)


def test_an_image_is_replaced_by_a_reference(multimodal):
    rebuilt, stored = _offload([AgentRequestImage(image_data="ZmFrZQ==", name="shot.png", mime_type="image/png")])

    [reference] = rebuilt
    assert isinstance(reference, AgentRequestAttachmentRef)
    assert reference.attachment_id == stored[0].attachment_id
    assert (stored[0].name, stored[0].mime_type) == ("shot.png", "image/png")


def test_a_file_is_replaced_by_a_reference(multimodal):
    rebuilt, stored = _offload([AgentRequestFile(file_data="ZmFrZQ==", name="report.pdf", mime_type="application/pdf")])

    assert isinstance(rebuilt[0], AgentRequestAttachmentRef)
    assert stored[0].mime_type == "application/pdf"


def test_other_requests_keep_their_place(multimodal):
    requests = [
        AgentRequestText(prompt="look at this"),
        AgentRequestImage(image_data="ZmFrZQ==", name="shot.png", mime_type="image/png"),
        AgentRequestAny(name="body", content={"raw": 1}),
    ]

    rebuilt, stored = _offload(requests)

    assert [type(r).__name__ for r in rebuilt] == ["AgentRequestText", "AgentRequestAttachmentRef", "AgentRequestAny"]
    assert len(stored) == 1


def test_a_missing_mime_type_gets_a_sensible_default(multimodal):
    _, stored = _offload(
        [
            AgentRequestImage(image_data="ZmFrZQ==", name="shot", mime_type=None),
            AgentRequestFile(file_data="ZmFrZQ==", name="blob", mime_type=None),
        ]
    )

    assert [s.mime_type for s in stored] == ["image/jpeg", "application/octet-stream"]


def test_a_text_only_request_list_is_returned_unchanged():
    requests = [AgentRequestText(prompt="hello")]
    rebuilt, stored = _offload(requests)
    assert rebuilt is requests and stored == []


def test_attachments_without_multimodal_raise_the_callers_message():
    with pytest.raises(ValueError, match=DISABLED):
        _offload([AgentRequestImage(image_data="ZmFrZQ==", name="shot.png", mime_type="image/png")])


def test_session_cache_is_refused(monkeypatch):
    # It writes into a session copy the reading process never sees, so the bytes vanish silently.
    monkeypatch.setenv("AK_MULTIMODAL__ENABLED", "true")
    monkeypatch.setenv("AK_MULTIMODAL__STORAGE_TYPE", "session_cache")
    AKConfig._reset()

    with pytest.raises(ValueError, match="session_cache"):
        _offload([AgentRequestText(prompt="hello")])


def test_has_attachments_ignores_empty_payloads():
    assert has_attachments([AgentRequestImage(image_data="ZmFrZQ==", name="s", mime_type="image/png")])
    assert not has_attachments([AgentRequestText(prompt="hello")])
    assert not has_attachments([AgentRequestAttachmentRef(attachment_id="a1")])


def test_the_thread_manager_still_returns_thread_attachments(multimodal, monkeypatch):
    """The shared helper was extracted from the thread path; that path keeps its own shape."""
    from agentkernel.integration.thread.manager import ConversationThreadManager
    from agentkernel.integration.thread.model import ThreadAttachment

    manager = object.__new__(ConversationThreadManager)
    rebuilt, references = manager.store_attachments("s1", [AgentRequestImage(image_data="ZmFrZQ==", name="shot.png", mime_type="image/png")])

    assert isinstance(rebuilt[0], AgentRequestAttachmentRef)
    assert isinstance(references[0], ThreadAttachment)
    assert references[0].attachment_id == rebuilt[0].attachment_id
