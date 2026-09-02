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
        if isinstance(req, AgentRequestImage) and req.image_data:
            data, att_type, name, mime_type = req.image_data, "image", req.name, req.mime_type or "image/jpeg"
        elif isinstance(req, AgentRequestFile) and req.file_data:
            data, att_type, name, mime_type = req.file_data, "file", req.name, req.mime_type or "application/octet-stream"
        else:
            rebuilt.append(req)
            continue
        attachment_id = manager.save_attachment(
            data=data,
            attachment_type=att_type,
            name=name,
            mime_type=mime_type,
            max_attachments=sys.maxsize,
        )
        stored.append(StoredAttachment(attachment_id=attachment_id, name=name, mime_type=mime_type))
        rebuilt.append(AgentRequestAttachmentRef(attachment_id=attachment_id))
        _log.debug(f"Stored attachment {attachment_id} ({name}) for session {session_id}")
    return rebuilt, stored
