"""Moving attachment bytes out of a request list and into the AttachmentStore.

Two surfaces need the same rewrite before an agent request leaves the process it was built in:
conversation threads (the bytes must not be re-sent on every turn) and messaging integrations
(the bytes must not ride the queue, whose brokers cap a message far below api.max_file_size).
Both replace each image/file request with an ``AgentRequestAttachmentRef`` carrying the stored
id, which ``MultimodalPreHook`` resolves later; no raw bytes travel past storage.
"""

import logging
import sys
from dataclasses import dataclass
from typing import List, Tuple

from ...config import AKConfig
from ...model import AgentRequest, AgentRequestAttachmentRef, AgentRequestFile, AgentRequestImage
from ..source import AttachmentSource

_log = logging.getLogger("ak.multimodal.offload")


@dataclass
class StoredAttachment:
    """One attachment that was moved into the AttachmentStore."""

    attachment_id: str
    name: str
    mime_type: str


def has_attachments(requests: List[AgentRequest]) -> bool:
    """Whether any request in the list carries attachment bytes."""
    return any((isinstance(req, AgentRequestImage) and req.image_data) or (isinstance(req, AgentRequestFile) and req.file_data) for req in requests)


def offload_attachments(
    session_id: str,
    requests: List[AgentRequest],
    *,
    attachments_disabled_error: str,
    session_cache_error: str,
) -> Tuple[List[AgentRequest], List[StoredAttachment]]:
    """Save each image/file request's bytes and replace it, in place, with a reference.

    Requests that carry no attachment bytes pass through unchanged and keep their order.

    ``AttachmentSource`` decides what each attachment's record holds and whether its request
    survives: base64 data is stored as bytes and its request replaced by a reference, while a
    remote reference (``http://``, ``https://``, ``s3://``, or a non-base64 ``data:`` URI) is
    stored as a url and its request travels on untouched for the adapter to resolve.
    Attachments saved here are exempt from the store's ``max_attachments`` eviction: they are
    part of a request that has not run yet, so evicting one would lose the user's input.

    The two rejections are caller-worded because the remedy differs per surface, and both are
    configuration errors rather than runtime failures:

    - multimodal disabled: there is nowhere to put the bytes.
    - ``storage_type: session_cache``: it writes into a session copy that the process which
      later reads the attachment never sees, so the bytes are silently lost.

    :param session_id: Session identifier the attachments are isolated under.
    :param requests: The request list to scan.
    :param attachments_disabled_error: Message raised when attachments are present while
        ``multimodal.enabled`` is false.
    :param session_cache_error: Message raised when ``multimodal.storage_type`` is
        ``session_cache``.
    :return: (rebuilt request list, references to the saved attachments).
    :raises ValueError: If attachments are present but cannot be stored (see above).
    """
    if not AKConfig.get().multimodal.enabled:
        if has_attachments(requests):
            raise ValueError(attachments_disabled_error)
        return requests, []
    if AKConfig.get().multimodal.storage_type == "session_cache":
        raise ValueError(session_cache_error)

    from .storage_manager import AttachmentStorageManager

    manager = AttachmentStorageManager(session_id=session_id)
    rebuilt: List[AgentRequest] = []
    stored: List[StoredAttachment] = []
    for req in requests:
        extracted = AttachmentSource.extract(req)
        if extracted is None:
            rebuilt.append(req)
            continue
        is_reference = not extracted.is_base64
        attachment_id = manager.save_attachment(
            data="" if is_reference else extracted.data,
            attachment_type=extracted.att_type,
            name=extracted.name,
            mime_type=extracted.mime_type,
            max_attachments=sys.maxsize,
            url=extracted.data if is_reference else None,
        )
        stored.append(StoredAttachment(attachment_id=attachment_id, name=extracted.name, mime_type=extracted.mime_type))
        # A remote reference must not become an AgentRequestAttachmentRef: MultimodalPreHook
        # strips every ref before the agent runs, so the attachment would reach the agent as
        # nothing at all. It travels on untouched and the adapter resolves it.
        rebuilt.append(req if is_reference else AgentRequestAttachmentRef(attachment_id=attachment_id))
        _log.debug(f"Stored attachment {attachment_id} ({extracted.name}) for session {session_id}")
    return rebuilt, stored
