"""Open Knowledge Format value types — the representation axis of the knowledge-base tier.

An OKF bundle is a directory tree of markdown files: YAML frontmatter plus a body, with the
file path as the concept's identity. These types are what a tree of such files parses into.

The shape here is driven by one OKF conformance rule: *a strict OKF reader is a
non-conformant OKF reader*. A consumer MUST NOT reject a concept for a missing optional
field or an unknown ``type``, and MUST NOT reject a bundle for a broken link or an unknown
frontmatter key. So nothing is dropped — unrecognised frontmatter lands in
:attr:`OKFConcept.extra`, and everything a reader wants to complain about becomes an
:class:`OKFDiagnostic` carried alongside the data rather than an exception raised instead
of it.

``trust`` and ``stale`` are advisory signals derived from the specified fields only. They
ride on every record the OKF backend returns and are never grounds for filtering.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TrustTier(str, Enum):
    """How thoroughly a concept has been checked; derived from ``verified`` and nothing else."""

    UNVERIFIED = "unverified"  # no verified entries
    MACHINE_CONFIRMED = "machine-confirmed"  # verified, but by no "human:" actor
    HUMAN_REVIEWED = "human-reviewed"  # at least one "human:" actor


class DiagnosticCode(str, Enum):
    """Every code an OKF reader emits.

    A constant source for the parser and the manager, which both emit codes and would
    otherwise repeat the strings. Deliberately NOT the annotation on
    :attr:`OKFDiagnostic.code`: a code from a future producer must still round-trip, so the
    field stays an open ``str`` and this enum gates nothing.
    """

    UNPARSEABLE_FRONTMATTER = "unparseable_frontmatter"  # absent, unparseable, or not a mapping
    MISSING_TYPE = "missing_type"  # the one required frontmatter key
    COMMA_IN_PATH = "comma_in_path"  # could never round-trip through fetch_kb's id list
    PATH_ESCAPE = "path_escape"  # a link or listed path leaves the bundle namespace
    VERSION_MISMATCH = "version_mismatch"  # bundle-root okf_version is present and not "0.2"
    INDEX_FRONTMATTER = "index_frontmatter"  # a non-root index.md carries frontmatter
    UNPARSEABLE_STALE_AFTER = "unparseable_stale_after"  # not an ISO-8601 timestamp
    COERCED_SCALAR = "coerced_scalar"  # a bare verified mapping or a scalar tags value
    TRUNCATED = "truncated"  # the walk stopped at max_concepts
    UNREADABLE = "unreadable"  # the store raised while reading a candidate file


class OKFDiagnostic(BaseModel):
    """One complaint about a bundle, carried rather than raised."""

    path: str  # bundle-relative path it concerns; "" for a bundle-level diagnostic
    code: str  # a DiagnosticCode value, but open so an unknown code round-trips
    message: str


class OKFConcept(BaseModel):
    """One parsed concept document: its frontmatter, its derived signals, and its body index."""

    path: str  # identity; bundle-relative, POSIX. There is no separate id field in OKF.

    # Identity family. Only `type` is required by the specification, and its values are an
    # open vocabulary invented by producers, so it stays a bare str.
    type: str
    title: str | None = None
    description: str | None = None
    resource: str | None = None
    tags: list[str] = Field(default_factory=list)

    # Lifecycle family. `status` (draft | stable | deprecated) is likewise open: an enum
    # would force either rejecting an unknown value or silently coercing it, and the
    # conformance rules forbid the first.
    status: str | None = None
    stale_after: str | None = None  # retained verbatim; `stale` below is the parsed answer

    # Provenance and trust families, carried as data. No reference field is ever
    # dereferenced anywhere in this layer.
    generated: dict[str, Any] = Field(default_factory=dict)  # {by, at}
    verified: list[dict[str, Any]] = Field(default_factory=list)  # [{by, at}]
    sources: list[dict[str, Any]] = Field(default_factory=list)

    # Computation family: runtime / parameters / computation / executor / attester, present
    # only on `type: Attested Computation`. Executing one is a sandbox concern, not a
    # knowledge-base concern, so these are carried and never acted on.
    computation: dict[str, Any] = Field(default_factory=dict)

    extra: dict[str, Any] = Field(default_factory=dict)  # every unrecognised frontmatter key, untouched

    trust: TrustTier = TrustTier.UNVERIFIED  # derived from `verified`
    stale: bool = False  # derived from `stale_after`

    # A manifest walk reads only a bounded prefix of each file, so it can index a body it
    # cannot retain. `body` is None and `links` empty in that case; `fetch` re-reads the
    # whole document and is the only operation whose records carry links.
    body: str | None = None
    body_tokens: set[str] = Field(default_factory=set)
    links: list[str] = Field(default_factory=list)


class OKFBundle(BaseModel):
    """A whole bundle as one in-process manifest, assembled by the OKF backend from a store walk."""

    concepts: dict[str, OKFConcept] = Field(default_factory=dict)  # keyed by path
    index_files: dict[str, str] = Field(default_factory=dict)  # directory ("" = root) -> index.md path
    log_files: list[str] = Field(default_factory=list)
    okf_version: str | None = None  # declared in the bundle-root index.md, if at all
    diagnostics: list[OKFDiagnostic] = Field(default_factory=list)
    truncated: bool = False  # the walk stopped at max_concepts
