"""Content routing in the `analyze_attachments` system tool, per stored-record shape."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.multimodal.storage import AttachmentStorageManager
from agentkernel.core.multimodal.storage.in_memory import InMemoryAttachmentStore
from agentkernel.core.multimodal.tools import analyze_attachments
from agentkernel.core.tool import ToolContext

BASE64 = "aW1n"
REMOTE_IMAGE = "https://example.com/cat.png"
REMOTE_PDF = "https://example.com/report.pdf"


def _llm_response(content):
    """Build a minimal litellm.completion response carrying the given content."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def tool_session():
    """A session with in-memory attachment storage and the ToolContext the tool reads."""
    original_enabled = AKConfig.get().multimodal.enabled
    original_storage = AKConfig.get().multimodal.storage_type
    AKConfig.get().multimodal.enabled = True
    AKConfig.get().multimodal.storage_type = "in_memory"
    InMemoryAttachmentStore._attachments.clear()
    InMemoryAttachmentStore._index.clear()

    session = Session("tool-session")
    context = ToolContext(runtime=None, agent=None, session=session, requests=[])
    context.set()
    yield session
    context.reset()

    AKConfig.get().multimodal.enabled = original_enabled
    AKConfig.get().multimodal.storage_type = original_storage
    InMemoryAttachmentStore._attachments.clear()
    InMemoryAttachmentStore._index.clear()


class _AnalyzeCall:
    """Shared driver for the test classes below: save a record, then read what the tool sends."""

    @staticmethod
    def save(session, name, mime_type, data="", url=None):
        """Store one attachment record and return its id."""
        return AttachmentStorageManager(session_id=session.id).save_attachment(
            data=data,
            attachment_type="image" if mime_type.startswith("image/") else "file",
            name=name,
            mime_type=mime_type,
            url=url,
        )

    @staticmethod
    def parts_sent(attachment_ids, prompt="describe these"):
        """Run the tool against a stubbed LLM and return the content parts it was given."""
        with patch("litellm.completion", return_value=_llm_response("analysis")) as completion:
            analyze_attachments(attachment_ids, prompt)
        return completion.call_args.kwargs["messages"][0]["content"]


class TestRemoteRecords(_AnalyzeCall):
    """Records holding an address, saved with an empty `data`."""

    def test_remote_image_is_sent_as_its_url_not_a_base64_wrapper(self, tool_session):
        att_id = self.save(tool_session, "cat.png", "image/png", url=REMOTE_IMAGE)

        parts = self.parts_sent([att_id])

        assert parts[1] == {"type": "image_url", "image_url": {"url": REMOTE_IMAGE}}

    def test_remote_non_image_is_sent_as_text_naming_its_address(self, tool_session):
        att_id = self.save(tool_session, "report.pdf", "application/pdf", url=REMOTE_PDF)

        parts = self.parts_sent([att_id])

        assert parts[1]["type"] == "text"
        assert REMOTE_PDF in parts[1]["text"]
        assert "report.pdf" in parts[1]["text"]

    def test_no_remote_record_reaches_the_base64_branches(self, tool_session):
        ids = [
            self.save(tool_session, "cat.png", "image/png", url=REMOTE_IMAGE),
            self.save(tool_session, "report.pdf", "application/pdf", url=REMOTE_PDF),
        ]

        parts = self.parts_sent(ids)

        assert not any("base64," in str(part) for part in parts)


class TestStoredRecords(_AnalyzeCall):
    """Records holding base64 bytes, saved with no url."""

    def test_stored_image_is_wrapped_as_a_data_uri(self, tool_session):
        att_id = self.save(tool_session, "pic.png", "image/png", data=BASE64)

        parts = self.parts_sent([att_id])

        assert parts[1] == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{BASE64}"}}

    def test_stored_pdf_is_sent_as_a_file_part(self, tool_session):
        att_id = self.save(tool_session, "doc.pdf", "application/pdf", data=BASE64)

        parts = self.parts_sent([att_id])

        assert parts[1]["type"] == "file"
        assert parts[1]["file"]["filename"] == "doc.pdf"
        assert parts[1]["file"]["file_data"] == f"data:application/pdf;base64,{BASE64}"

    def test_stored_other_type_is_named_in_text_rather_than_shown(self, tool_session):
        att_id = self.save(tool_session, "rows.csv", "text/csv", data=BASE64)

        parts = self.parts_sent([att_id])

        assert parts[1]["type"] == "text"
        assert "rows.csv" in parts[1]["text"]
        assert BASE64 not in parts[1]["text"]

    def test_the_prompt_leads_the_content(self, tool_session):
        att_id = self.save(tool_session, "pic.png", "image/png", data=BASE64)

        parts = self.parts_sent([att_id], prompt="what is in this?")

        assert parts[0] == {"type": "text", "text": "what is in this?"}
        assert len(parts) == 2


class TestGuards(_AnalyzeCall):
    """The two early returns, which never reach the store or the LLM."""

    def test_no_ids_returns_without_calling_the_llm(self):
        with patch("litellm.completion") as completion:
            result = analyze_attachments([], "describe these")

        assert result == "No attachments provided"
        completion.assert_not_called()

    def test_unknown_id_returns_without_calling_the_llm(self, tool_session):
        with patch("litellm.completion") as completion:
            result = analyze_attachments(["does-not-exist"], "describe these")

        assert result == "No attachments found for the given IDs in this session"
        completion.assert_not_called()
