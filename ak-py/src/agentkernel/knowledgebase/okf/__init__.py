"""Open Knowledge Format — the representation axis of the knowledge-base tier.

Everything here is pure: text in, objects out. The package imports no ``DocumentStore`` and
opens no connection, which is what lets one OKF reader serve a bundle from a local directory
and from an S3 prefix without changing.

``OKFManager``, the backend that walks a store with these functions, is deliberately absent
from these exports and lives in ``agentkernel.knowledgebase.okf.manager``, so importing this
package stays free of the storage axis.
"""

from .model import DiagnosticCode, OKFBundle, OKFConcept, OKFDiagnostic, TrustTier
from .parser import (
    BODY_INDEX_MAX_BYTES,
    FRONTMATTER_MAX_BYTES,
    INDEX_FILENAME,
    LOG_FILENAME,
    OKF_VERSION,
    RESERVED_FILENAMES,
    decode_document,
    derive_trust,
    extract_links,
    is_reserved,
    is_stale,
    parse_concept,
    parse_index,
    split_frontmatter,
    tokenise,
)

__all__ = [
    "BODY_INDEX_MAX_BYTES",
    "FRONTMATTER_MAX_BYTES",
    "INDEX_FILENAME",
    "LOG_FILENAME",
    "OKF_VERSION",
    "RESERVED_FILENAMES",
    "DiagnosticCode",
    "OKFBundle",
    "OKFConcept",
    "OKFDiagnostic",
    "TrustTier",
    "decode_document",
    "derive_trust",
    "extract_links",
    "is_reserved",
    "is_stale",
    "parse_concept",
    "parse_index",
    "split_frontmatter",
    "tokenise",
]
