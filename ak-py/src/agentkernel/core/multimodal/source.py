"""
Attachment source-form classification, shared by every path that takes bytes off a request.

An attachment's data field arrives in one of several shapes — bare base64, a `data:` URI with or
without the base64 marker, or a remote reference — and what a caller may do with it depends
entirely on which. `AttachmentSource` answers that question in one place so the direct path
(`MultimodalPreHook`) and the thread path (`ConversationThreadManager.store_attachments`) cannot
answer it differently: a source form handled by one and mishandled by the other is exactly the
class of bug this module exists to prevent.
"""

from dataclasses import dataclass
from typing import Optional

from ..model import AgentRequest, AgentRequestFile, AgentRequestImage

IMAGE_DEFAULT_MIME = "image/jpeg"
FILE_DEFAULT_MIME = "application/octet-stream"


@dataclass(frozen=True)
class ExtractedAttachment:
    """
    One attachment's data pulled off a request, with its source form resolved.

    `is_base64` is what decides whether a caller may store or decode the data, and it is False for
    two different sources:

    * **A remote reference** (`http://`, `https://`, `s3://`) — not fetched, because that would put
      network I/O and SSRF exposure inside a system pre-hook running on every request.
    * **A `data:` URI without the base64 marker** (`data:text/plain,hello%20world`) — its bytes are
      percent-encoded text, so storing them as base64 would store the wrong thing.

    Either way the originating request must survive into the list the agent sees, so the adapter
    receives the attachment and resolves it itself.
    """

    data: str
    att_type: str
    name: str
    mime_type: str
    is_base64: bool


class AttachmentSource:
    """Classifier for the source form of an attachment carried on a request."""

    @staticmethod
    def extract(req: AgentRequest) -> Optional[ExtractedAttachment]:
        """
        Extract attachment data from a request if it is an image or file, and classify its source.

        :param req: An agent request.
        :return: The extracted attachment, or None if the request carries no attachment data.
        """
        if isinstance(req, AgentRequestImage) and req.image_data:
            resolved = AttachmentSource.resolve(req.image_data, req.mime_type, IMAGE_DEFAULT_MIME)
            if resolved is None:
                return None
            data, mime_type, is_base64 = resolved
            return ExtractedAttachment(data, "image", req.name, mime_type, is_base64)
        if isinstance(req, AgentRequestFile) and req.file_data:
            resolved = AttachmentSource.resolve(req.file_data, req.mime_type, FILE_DEFAULT_MIME)
            if resolved is None:
                return None
            data, mime_type, is_base64 = resolved
            return ExtractedAttachment(data, "file", req.name, mime_type, is_base64)
        return None

    @staticmethod
    def resolve(source: str, declared_mime: Optional[str], default_mime: str) -> Optional[tuple[str, str, bool]]:
        """
        Resolve one attachment source string into its bytes, its mime type, and whether those bytes are base64.

        - `http://`, `https://`, `s3://`: a remote reference, returned unchanged and not base64.
        - `data:<mime>;base64,<payload>`: split into the payload plus the mime type the URI itself
          declares. The URI wins over `declared_mime` and over `default_mime`, neither of which is
          consulted unless the URI omits its own — this is what stops a PNG being stored as JPEG.
        - Anything else is treated as bare base64, keeping `declared_mime` or `default_mime`.

        A `data:` URI with nothing after the comma resolves to `None`: it carries no bytes, so it is
        the same case as an empty `image_data`, and the caller drops it rather than handing an adapter
        a payloadless URI.

        A `data:` URI that is not base64-encoded is passed through rather than decoded, since its
        bytes are not what a caller would store. Per RFC 2397 the marker is the final parameter of
        the header, so a header that merely contains the text `;base64` does not qualify.

        Scheme and header matching is case-insensitive, since URI schemes (RFC 3986 §3.1), media
        types and parameter names all are. Only the leading bytes and the short header are folded —
        an attachment payload can be megabytes of base64, and lowercasing it would copy the lot.

        :param source: The raw source string from the request.
        :param declared_mime: The request's own mime_type, if it set one.
        :param default_mime: Fallback when neither the source nor the request declares one.
        :return: (data, mime_type, is_base64), or None when the source carries no bytes at all.
        """
        scheme = source[:8].lower()  # 8 == len("https://"), the longest prefix matched below

        if scheme.startswith(("http://", "https://", "s3://")):
            return source, declared_mime or default_mime, False

        if scheme.startswith("data:"):
            header, _, payload = source.partition(",")
            if not payload:
                return None
            if not header.lower().endswith(";base64"):
                return source, declared_mime or default_mime, False
            uri_mime = header[len("data:") :].split(";", 1)[0].lower()
            return payload, uri_mime or declared_mime or default_mime, True

        return source, declared_mime or default_mime, True
