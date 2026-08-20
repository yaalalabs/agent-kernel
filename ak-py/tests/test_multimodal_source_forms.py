"""
Attachment source forms through MultimodalPreHook (spec #523 §8).

An attachment's data field can arrive in five shapes, and before #523 only the first worked. The
other four were passed to storage and to the description LLM verbatim, so a `data:` URI was stored
with its header treated as base64 and labelled `image/jpeg` whatever it actually was, and a URL was
stored as though the URL text were the image.

The half of the fix that is easy to lose is in the filter loop rather than in the classifier: a
request the hook declines must still reach the agent. Declining to describe a URL and *also*
stripping it is worse than the original corruption, because the model then never sees the
attachment at all. `test_*_is_retained_*` are the guards for that.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentRequestFile, AgentRequestImage, AgentRequestText
from agentkernel.core.multimodal.hooks import MultimodalPreHook
from agentkernel.core.multimodal.storage.in_memory import InMemoryAttachmentStore

REMOTE_SOURCES = ["http://example.com/cat.png", "https://example.com/cat.png", "s3://bucket/cat.png"]
# Schemes are case-insensitive per RFC 3986 §3.1, so these are valid URLs too.
REMOTE_SOURCES_ODD_CASE = ["HTTP://example.com/cat.png", "HTTPS://EXAMPLE.COM/CAT.PNG", "S3://bucket/cat.png", "Https://example.com/cat.png"]


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
    with patch.object(hook, "_describe_attachment_briefly", new=AsyncMock(return_value="a small test image")) as describe:
        result = asyncio.run(hook.on_run(session, agent=None, requests=requests))
    return result, describe


def _stored():
    """Every attachment the hook saved, in insertion order."""
    return list(InMemoryAttachmentStore._attachments.values())


class TestConsumableSourceForms:
    """Bare base64 and `data:` URIs: described, stored, and stripped from the request list."""

    def test_bare_base64_is_stored_as_before(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestText(prompt="what is this?"), AgentRequestImage(image_data="aW1n", name="pic.png", mime_type="image/png")]

        result, _ = _run_hook(session, requests)

        assert [type(r) for r in result] == [AgentRequestText]
        assert "a small test image" in result[0].prompt
        assert len(_stored()) == 1
        assert _stored()[0]["data"] == "aW1n"
        assert _stored()[0]["mime_type"] == "image/png"

    def test_bare_base64_without_mime_falls_back_to_the_type_default(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestImage(image_data="aW1n", name="pic.bin")]

        _run_hook(session, requests)

        # Nothing better is available for a bare payload, so the type default stands.
        assert _stored()[0]["mime_type"] == "image/jpeg"

    def test_data_uri_is_split_into_payload_and_its_own_mime_type(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestImage(image_data="data:image/webp;base64,aW1n", name="pic.webp")]

        _run_hook(session, requests)

        # The header must not reach storage, and the mime type comes from the URI.
        assert _stored()[0]["data"] == "aW1n"
        assert _stored()[0]["mime_type"] == "image/webp"

    def test_data_uri_mime_type_beats_the_requests_declared_one(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestImage(image_data="data:image/webp;base64,aW1n", name="pic.webp", mime_type="image/jpeg")]

        _run_hook(session, requests)

        # This is the case that used to be mislabelled: the old code took `mime_type or "image/jpeg"`
        # and never looked inside the URI.
        assert _stored()[0]["mime_type"] == "image/webp"

    def test_data_uri_without_its_own_mime_falls_back_to_the_declared_one(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestImage(image_data="data:;base64,aW1n", name="pic.webp", mime_type="image/webp")]

        _run_hook(session, requests)

        assert _stored()[0]["data"] == "aW1n"
        assert _stored()[0]["mime_type"] == "image/webp"

    @pytest.mark.parametrize("source", ["DATA:image/png;base64,aW1n", "data:IMAGE/PNG;BASE64,aW1n", "Data:Image/Png;Base64,aW1n"])
    def test_data_uri_is_split_whatever_the_header_case(self, multimodal_enabled, source):
        session = Session("s1")
        requests = [AgentRequestImage(image_data=source, name="pic.png")]

        _run_hook(session, requests)

        # The mime type is normalised to lower case; the payload keeps its case, since base64 is
        # case-sensitive and folding it would corrupt the bytes.
        assert _stored()[0]["data"] == "aW1n"
        assert _stored()[0]["mime_type"] == "image/png"

    def test_mixed_case_base64_payload_is_stored_verbatim(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestImage(image_data="aW1nQUJDeHl6", name="pic.png", mime_type="image/png")]

        _run_hook(session, requests)

        assert _stored()[0]["data"] == "aW1nQUJDeHl6"

    def test_data_uri_file_is_split_the_same_way(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestFile(file_data="data:application/pdf;base64,cGRm", name="doc.pdf")]

        _run_hook(session, requests)

        assert _stored()[0]["data"] == "cGRm"
        assert _stored()[0]["mime_type"] == "application/pdf"
        assert _stored()[0]["type"] == "file"

    def test_description_is_generated_from_the_decoded_payload_not_the_uri(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestImage(image_data="data:image/webp;base64,aW1n", name="pic.webp")]

        _, describe = _run_hook(session, requests)

        # The LLM must see the payload and the real mime type, or the description is of nonsense.
        describe.assert_awaited_once_with(data="aW1n", mime_type="image/webp")


class TestRemoteSourceForms:
    """http, https and s3: neither described nor stored, and still handed to the agent."""

    @pytest.mark.parametrize("source", REMOTE_SOURCES)
    def test_remote_image_is_retained_and_left_untouched(self, multimodal_enabled, source):
        session = Session("s1")
        image = AgentRequestImage(image_data=source, name="cat.png")
        requests = [AgentRequestText(prompt="what is this?"), image]

        result, describe = _run_hook(session, requests)

        # Retained, and the same object — not a rebuilt copy that could have lost a field.
        assert result[1] is image
        assert result[1].image_data == source
        # Neither described nor stored.
        describe.assert_not_awaited()
        assert _stored() == []
        # No description text was injected, so the prompt is untouched.
        assert result[0].prompt == "what is this?"

    @pytest.mark.parametrize("source", REMOTE_SOURCES)
    def test_remote_file_is_retained_and_left_untouched(self, multimodal_enabled, source):
        session = Session("s1")
        file_req = AgentRequestFile(file_data=source, name="doc.pdf")

        result, describe = _run_hook(session, [file_req])

        assert result == [file_req]
        describe.assert_not_awaited()
        assert _stored() == []

    @pytest.mark.parametrize("source", REMOTE_SOURCES_ODD_CASE)
    def test_remote_reference_is_recognised_whatever_the_scheme_case(self, multimodal_enabled, source):
        session = Session("s1")
        image = AgentRequestImage(image_data=source, name="cat.png")

        result, describe = _run_hook(session, [image])

        # Case-folding the scheme is the difference between passing a URL to the adapter and storing
        # the URL text as though it were the image's bytes.
        assert result == [image]
        describe.assert_not_awaited()
        assert _stored() == []

    def test_a_data_uri_whose_header_only_contains_the_marker_is_not_treated_as_base64(self, multimodal_enabled):
        session = Session("s1")
        # ";base64" appears in the header but is not its final parameter, so per RFC 2397 the payload
        # is not base64. A substring check would decode it and store the wrong bytes.
        image = AgentRequestImage(image_data="data:x;base64extra,cGRm", name="odd.bin")

        result, describe = _run_hook(session, [image])

        assert result == [image]
        describe.assert_not_awaited()
        assert _stored() == []

    def test_a_non_base64_data_uri_is_retained_rather_than_stored_as_base64(self, multimodal_enabled):
        session = Session("s1")
        image = AgentRequestImage(image_data="data:text/plain,hello", name="note.txt")

        result, describe = _run_hook(session, [image])

        # Its bytes are percent-encoded text, not base64, so storing it would store the wrong thing.
        assert result == [image]
        describe.assert_not_awaited()
        assert _stored() == []


class TestMixedAndEdgeCases:

    def test_a_consumed_and_a_declined_attachment_in_one_request(self, multimodal_enabled):
        session = Session("s1")
        remote = AgentRequestImage(image_data="https://example.com/cat.png", name="cat.png")
        requests = [
            AgentRequestText(prompt="compare these"),
            AgentRequestImage(image_data="data:image/png;base64,aW1n", name="local.png"),
            remote,
        ]

        result, describe = _run_hook(session, requests)

        # The local one is stored and stripped; the remote one survives beside the text.
        assert [type(r) for r in result] == [AgentRequestText, AgentRequestImage]
        assert result[1] is remote
        assert len(_stored()) == 1
        assert _stored()[0]["data"] == "aW1n"
        # Only the stored attachment is described, and only it appears in the injected text.
        assert describe.await_count == 1
        assert "a small test image" in result[0].prompt
        assert "example.com" not in result[0].prompt

    def test_attachment_with_no_data_is_still_dropped(self, multimodal_enabled):
        session = Session("s1")
        requests = [AgentRequestText(prompt="hi"), AgentRequestImage(image_data="", name="empty.png")]

        result, describe = _run_hook(session, requests)

        # Pinning pre-existing behaviour: there is nothing to store and nothing to forward, so the
        # request is consumed rather than retained. Retaining it would make adapters raise.
        assert result == [requests[0]]
        describe.assert_not_awaited()

    @pytest.mark.parametrize("source", ["data:image/png;base64,", "data:;base64,", "DATA:image/png;BASE64,"])
    def test_data_uri_with_an_empty_payload_is_dropped_like_no_data(self, multimodal_enabled, source):
        session = Session("s1")
        requests = [AgentRequestText(prompt="hi"), AgentRequestImage(image_data=source, name="empty.png")]

        result, describe = _run_hook(session, requests)

        # A well-formed base64 `data:` URI carrying nothing after the comma holds exactly as many
        # bytes as image_data="" above, so it takes the same path. Retaining it would hand an adapter
        # a payloadless URI, which is the failure the test above exists to prevent.
        assert result == [requests[0]]
        assert len(_stored()) == 0
        describe.assert_not_awaited()

    def test_data_uri_that_is_not_base64_is_retained_with_its_payload(self, multimodal_enabled):
        session = Session("s1")
        # The other half of the same condition, and it must not be dropped: the payload is real
        # content, just not base64, so decoding it would store the wrong bytes. The adapter decides.
        plain = AgentRequestFile(file_data="data:text/plain,hello%20world", name="note.txt")
        requests = [AgentRequestText(prompt="hi"), plain]

        result, describe = _run_hook(session, requests)

        assert result == [requests[0], plain]
        assert result[1] is plain
        assert len(_stored()) == 0
        describe.assert_not_awaited()

    def test_text_requests_are_never_recorded_as_consumed(self, multimodal_enabled):
        session = Session("s1")
        text = AgentRequestText(prompt="hi")
        remote = AgentRequestImage(image_data="https://example.com/cat.png", name="cat.png")

        hook = MultimodalPreHook()
        with patch.object(hook, "_describe_attachment_briefly", new=AsyncMock(return_value="d")):
            config = AKConfig.get().multimodal
            _, consumed = asyncio.run(hook._process_attachments(session, [text, remote], config))

        # consumed must hold only attachment requests the hook took over. A text request landing in
        # there is harmless today only because the filter loop re-checks the type; the set's meaning
        # is what this pins.
        assert consumed == set()

    def test_remote_only_request_needs_no_synthetic_text(self, multimodal_enabled):
        session = Session("s1")
        image = AgentRequestImage(image_data="s3://bucket/cat.png", name="cat.png")

        result, _ = _run_hook(session, [image])

        # With no descriptions there is nothing to inject, so the attachments-only branch that
        # appends a synthetic AgentRequestText must not fire.
        assert result == [image]

    def test_hook_is_inert_when_multimodal_is_disabled(self, multimodal_enabled):
        AKConfig.get().multimodal.enabled = False
        session = Session("s1")
        requests = [AgentRequestImage(image_data="data:image/png;base64,aW1n", name="pic.png")]

        result, describe = _run_hook(session, requests)

        assert result == requests
        describe.assert_not_awaited()
        assert _stored() == []
