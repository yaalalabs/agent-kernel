"""Parsing OKF documents: bytes or text in, :class:`OKFConcept` out.

This module is deliberately store-free and network-free. :class:`OKFParserUtil` takes a
bundle-relative path and the document text, and returns objects. That is what lets one OKF
reader serve a bundle from a local directory in development and from an S3 prefix in
production without either the reader or the store changing — and it is asserted by a test
that fails if importing this module pulls in ``urllib``, ``httpx``, or
``agentkernel.knowledgebase.store``.

Nothing here raises on a bad document. The OKF conformance rules are tolerance rules — a
consumer MUST NOT reject a concept for a missing optional field or an unknown ``type``, and
MUST NOT reject a bundle for a broken link or an unknown frontmatter key — so a malformed
document yields ``None`` plus a diagnostic and the bundle around it still loads. The three
conditions that skip a concept are enumerated on :meth:`OKFParserUtil.parse_concept`; every
other surprise is carried.

Reference fields (``resource``, ``sources[].resource``, ``computation``) are carried as
data and are never dereferenced, here or anywhere else in the knowledge-base tier.
"""

import posixpath
import re
from datetime import datetime, timezone
from typing import Any

import yaml
from pydantic import ValidationError

from .model import DiagnosticCode, OKFConcept, OKFDiagnostic, TrustTier

# The manifest walk reads one bounded prefix per concept rather than whole objects, which is
# what makes an eager frontmatter pass affordable over S3. 16 KiB covers any realistic
# frontmatter block; the extra 8 KiB is the body window the token index is built from.
FRONTMATTER_MAX_BYTES = 16 * 1024
BODY_INDEX_MAX_BYTES = 8 * 1024

# The only version this reader targets. A v0.1 bundle still loads: the two v0.1 fallbacks
# (a legacy `timestamp` key, a body `# Citations` list) are MAY in the specification, and
# declining them is therefore conformant. `timestamp` lands in `extra` like any other
# unrecognised key, and `# Citations` stays ordinary body text.
OKF_VERSION = "0.2"

# Reserved at every directory level, not just the bundle root, and never parsed as concepts.
INDEX_FILENAME = "index.md"
LOG_FILENAME = "log.md"
RESERVED_FILENAMES = frozenset({INDEX_FILENAME, LOG_FILENAME})

# The actor convention: "<producer>/<version>" for agents, "human:<id>" for people,
# "process:<id>" for automation. Human review is detected by this prefix and nothing else.
_HUMAN_ACTOR_PREFIX = "human:"

_DELIMITER = "---"

# Frontmatter keys with defined meaning. Anything outside this set is carried into `extra`.
_COMPUTATION_KEYS = ("runtime", "parameters", "computation", "executor", "attester")
_KNOWN_KEYS = frozenset(
    {"type", "title", "description", "resource", "tags", "status", "stale_after", "generated", "verified", "sources", *_COMPUTATION_KEYS}
)

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# Anchored, and requires the scheme to be followed by ":", so "https://x" and "mailto:a" are
# recognised as absolute while "notes/q1.md" and "./sibling.md" are not.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

_TOKEN_SEPARATOR = re.compile(r"[^a-z0-9]+")
_MIN_TOKEN_LENGTH = 2


class OKFParserUtil:
    """
    Turns OKF document text into concepts, links, trust tiers and staleness.

    Every method is static because parsing an OKF document depends on nothing but the
    document: there is no connection, no cache, and no configuration to hold. Grouping them
    on one class keeps the reserved-file rules, the tolerance rules and the tokeniser under
    a single owner, which is what the manifest walk in ``OKFManager`` reaches for.
    """

    @staticmethod
    def decode_document(data: bytes) -> str:
        """
        Decode document bytes to text without ever raising.

        ``errors="replace"`` is load-bearing rather than defensive: the manifest walk reads
        a bounded *prefix* of each file, which can cut a multi-byte character in half. A
        strict decode would abort the walk over one non-ASCII concept.

        The codec is ``utf-8-sig`` for the same reason ``is_reserved`` compares
        case-insensitively: bundles travel as git repos and tarballs from Windows editors, and
        under plain ``utf-8`` a leading byte-order marker becomes content — enough to make the
        opening ``---`` unrecognisable and drop the whole concept.

        :param data: Raw document bytes, possibly a truncated prefix.
        :return: Decoded text, without any leading byte-order marker.
        """
        return data.decode("utf-8-sig", errors="replace")

    @staticmethod
    def tokenise(text: str) -> set[str]:
        """
        Reduce text to the token set the lexical ranker matches on.

        Defined here, next to the body index it fills, so the query side and the index side
        provably share one definition — that shared definition is what makes search ranking
        reproducible across processes.

        :param text: Any text; empty and ``None``-ish values are tolerated.
        :return: Lowercase tokens of at least two characters.
        """
        if not text:
            return set()
        return {token for token in _TOKEN_SEPARATOR.split(text.lower()) if len(token) >= _MIN_TOKEN_LENGTH}

    @staticmethod
    def is_reserved(path: str) -> bool:
        """
        Report whether a path names a reserved OKF file.

        The comparison is case-insensitive because bundles travel as git repos and tarballs
        across case-insensitive filesystems, where treating ``Index.md`` as a concept would
        mint a concept colliding with the directory's index.

        :param path: Bundle-relative path.
        :return: True for ``index.md`` or ``log.md`` at any level of the tree.
        """
        return posixpath.basename(path.replace("\\", "/")).lower() in RESERVED_FILENAMES

    @staticmethod
    def split_frontmatter(data: str) -> tuple[str | None, str]:
        """
        Split a document into its YAML frontmatter block and its body.

        The document must open with ``---`` on its own first line, and the block ends at the
        next line that is exactly ``---``. A missing opening or closing delimiter is not an
        error here — the caller decides what an absent block means, which differs between a
        concept (skipped) and an ``index.md`` (permitted).

        :param data: Whole document text, or a bounded prefix of one.
        :return: The frontmatter text and the body; the frontmatter is ``None`` when there is
            no complete block, in which case the body is the input unchanged.
        """
        lines = data.splitlines(keepends=True)
        if not lines or lines[0].rstrip() != _DELIMITER:
            return None, data

        for index in range(1, len(lines)):
            if lines[index].rstrip() == _DELIMITER:
                return "".join(lines[1:index]), "".join(lines[index + 1 :])
        return None, data

    @staticmethod
    def derive_trust(verified: list[dict[str, Any]]) -> TrustTier:
        """
        Derive a concept's trust tier from its ``verified`` entries and nothing else.

        Not from ``generated``, not from ``status``, not from staleness. The tier is an
        advisory signal that rides on every record; it is never grounds for filtering one out.

        :param verified: The concept's ``verified`` list, possibly empty.
        :return: The derived tier.
        """
        if not verified:
            return TrustTier.UNVERIFIED

        for entry in verified:
            actor = entry.get("by") if isinstance(entry, dict) else None
            if isinstance(actor, str) and actor.startswith(_HUMAN_ACTOR_PREFIX):
                return TrustTier.HUMAN_REVIEWED
        return TrustTier.MACHINE_CONFIRMED

    @staticmethod
    def is_stale(stale_after: str | None, now: datetime) -> tuple[bool, list[OKFDiagnostic]]:
        """
        Decide whether a concept has passed its ``stale_after`` deadline.

        ``now`` is injected rather than read from the clock so the answer is deterministic
        under test. A naive deadline is read as UTC, since OKF timestamps are ISO-8601
        instants.

        :param stale_after: The verbatim frontmatter value, or ``None``.
        :param now: The instant to compare against.
        :return: Whether the concept is stale, and any diagnostics raised deciding that. An
            unparseable deadline yields ``False`` — a concept is never assumed stale.
        """
        if stale_after is None:
            return False, []

        text = str(stale_after).strip()
        if not text:
            return False, []

        # fromisoformat gained trailing-"Z" support in 3.11, but the substitution keeps the
        # behaviour explicit and independent of that.
        candidate = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        try:
            deadline = datetime.fromisoformat(candidate)
        except ValueError:
            message = f"stale_after is not an ISO-8601 timestamp: {stale_after!r}"
            return False, [OKFParserUtil._diagnostic("", DiagnosticCode.UNPARSEABLE_STALE_AFTER, message)]

        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        reference = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        return deadline < reference, []

    @staticmethod
    def extract_links(concept_path: str, body: str) -> tuple[list[str], list[OKFDiagnostic]]:
        """
        Extract the bundle-internal markdown links that form the OKF graph.

        OKF has no typed edges: a relationship *is* a markdown link, in one of two forms —
        bundle-absolute (``/tables/customers.md``) or relative (``./other.md``). Link
        semantics live in the surrounding prose.

        A broken link is kept: it is resolved to a bundle-relative path but never checked
        against a store, which is both a conformance MUST and the reason this module needs no
        store. Only a link escaping the bundle namespace is dropped.

        Containment is re-derived here rather than borrowed from
        ``DocumentStore.normalise_relative`` so that ``okf/`` keeps its zero-dependency on
        ``store/``; the two definitions agree, and the store enforces its own on every read.

        :param concept_path: Bundle-relative path of the document the body came from, used to
            resolve relative targets.
        :param body: The document body.
        :return: The linked paths in first-occurrence order without duplicates, and any
            diagnostics for targets that escaped the bundle.
        """
        links: list[str] = []
        diagnostics: list[OKFDiagnostic] = []
        seen: set[str] = set()
        directory = posixpath.dirname(concept_path)

        for match in _LINK.finditer(body or ""):
            target = match.group(1)
            # An absolute URL is a reference out of the bundle, not an edge within it, and is
            # never dereferenced anywhere in this layer.
            if _SCHEME.match(target):
                continue

            # A fragment or query addresses a place *inside* a document, so `./x.md#columns`
            # is the same edge as `./x.md`. Both are stripped before the suffix test, which
            # would otherwise drop every section link from the graph without a diagnostic.
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target.endswith(".md"):
                continue

            raw = target.lstrip("/") if target.startswith("/") else posixpath.join(directory, target)
            resolved = posixpath.normpath(raw)
            if resolved == ".." or resolved.startswith("../"):
                message = f"link escapes the bundle namespace: {target!r}"
                diagnostics.append(OKFParserUtil._diagnostic(concept_path, DiagnosticCode.PATH_ESCAPE, message))
                continue

            if resolved not in seen:
                seen.add(resolved)
                links.append(resolved)
        return links, diagnostics

    @staticmethod
    def parse_concept(path: str, data: str, *, body_complete: bool, now: datetime | None = None) -> tuple[OKFConcept | None, list[OKFDiagnostic]]:
        """
        Parse one concept document.

        A concept is skipped — ``None`` returned, bundle unaffected — on exactly three
        conditions: a ``,`` in its path, which could never round-trip through the comma-split
        id list the fetch tool takes; frontmatter that is absent, unparseable, or not a
        mapping; and a missing or empty ``type``, the one key OKF requires. Everything else is
        carried: unknown keys reach ``extra`` untouched, an unknown ``type`` value is kept
        verbatim, and a scalar where a collection was expected is normalised with a diagnostic.

        :param path: Bundle-relative POSIX path, which is the concept's identity.
        :param data: Document text — the whole document, or the bounded prefix the walk read.
        :param body_complete: Whether ``data`` holds the whole document. When it does not,
            ``body`` and ``links`` are left empty, because a truncated body would yield a
            truncated link set; ``body_tokens`` is still built from what was read.
        :param now: The instant staleness is judged against; defaults to the current UTC time.
        :return: The concept (or ``None`` if skipped) and every diagnostic raised parsing it.
        """
        if "," in path:
            message = f"concept path contains ',', which cannot round-trip through a fetch id list: {path!r}"
            return None, [OKFParserUtil._diagnostic(path, DiagnosticCode.COMMA_IN_PATH, message)]

        frontmatter_text, body = OKFParserUtil.split_frontmatter(data)
        if frontmatter_text is None:
            message = "document has no complete '---' frontmatter block"
            return None, [OKFParserUtil._diagnostic(path, DiagnosticCode.UNPARSEABLE_FRONTMATTER, message)]

        try:
            loaded = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as error:
            message = f"frontmatter is not valid YAML: {error}"
            return None, [OKFParserUtil._diagnostic(path, DiagnosticCode.UNPARSEABLE_FRONTMATTER, message)]

        if not isinstance(loaded, dict):
            message = f"frontmatter is not a mapping: {type(loaded).__name__}"
            return None, [OKFParserUtil._diagnostic(path, DiagnosticCode.UNPARSEABLE_FRONTMATTER, message)]

        concept_type = loaded.get("type")
        if not isinstance(concept_type, str) or not concept_type.strip():
            message = f"'type' is required and must be a non-empty string, got {concept_type!r}"
            return None, [OKFParserUtil._diagnostic(path, DiagnosticCode.MISSING_TYPE, message)]

        diagnostics: list[OKFDiagnostic] = []
        tags = OKFParserUtil._as_tags(path, loaded.get("tags"), diagnostics)
        verified = OKFParserUtil._as_verified(path, loaded.get("verified"), diagnostics)

        stale_after = OKFParserUtil._as_optional_str(loaded.get("stale_after"))
        stale, stale_diagnostics = OKFParserUtil.is_stale(stale_after, now or datetime.now(timezone.utc))
        # is_stale cannot know the path its signature does not carry, so it stamps "" and the
        # caller, which does know, re-stamps.
        diagnostics.extend(diagnostic.model_copy(update={"path": path}) for diagnostic in stale_diagnostics)

        links: list[str] = []
        if body_complete:
            links, link_diagnostics = OKFParserUtil.extract_links(path, body)
            diagnostics.extend(link_diagnostics)

        try:
            concept = OKFConcept(
                path=path,
                type=concept_type,
                title=OKFParserUtil._as_optional_str(loaded.get("title")),
                description=OKFParserUtil._as_optional_str(loaded.get("description")),
                resource=OKFParserUtil._as_optional_str(loaded.get("resource")),
                tags=tags,
                status=OKFParserUtil._as_optional_str(loaded.get("status")),
                stale_after=stale_after,
                generated=OKFParserUtil._as_mapping(loaded.get("generated")),
                verified=verified,
                sources=OKFParserUtil._as_mapping_list(loaded.get("sources")),
                computation={key: loaded[key] for key in _COMPUTATION_KEYS if key in loaded},
                extra={str(key): value for key, value in loaded.items() if key not in _KNOWN_KEYS},
                trust=OKFParserUtil.derive_trust(verified),
                stale=stale,
                body=body if body_complete else None,
                body_tokens=OKFParserUtil.tokenise(body),
                links=links,
            )
        except ValidationError as error:
            # A backstop, not a normal path: the coercions above cover every shape seen in the
            # wild, and a concept that still fails must be skipped rather than raised, or one
            # odd document would abort a whole bundle walk.
            message = f"frontmatter could not be modelled: {error}"
            return None, [OKFParserUtil._diagnostic(path, DiagnosticCode.UNPARSEABLE_FRONTMATTER, message)]

        return concept, diagnostics

    @staticmethod
    def parse_index(path: str, data: str, *, is_root: bool) -> tuple[str, str | None, list[OKFDiagnostic]]:
        """
        Parse a reserved ``index.md``: its curated listing, and the bundle version if it declares one.

        An index carries no frontmatter, except at the bundle root where ``okf_version`` is
        the single permitted key. Other keys there are unrecognised content, which tolerance
        says to carry rather than reject, so they draw no diagnostic. An index elsewhere
        carrying frontmatter draws one — and its body is still used, because rejecting a
        curated listing over a stray block would lose more than it protects.

        :param path: Bundle-relative path of the index file.
        :param data: The index document text.
        :param is_root: Whether this index sits at the bundle root.
        :return: The body to serve as the curated listing, the declared ``okf_version`` if
            any, and any diagnostics.
        """
        frontmatter_text, body = OKFParserUtil.split_frontmatter(data)
        if frontmatter_text is None:
            return data, None, []

        if not is_root:
            message = "index.md outside the bundle root carries a frontmatter block; the body is still used"
            return body, None, [OKFParserUtil._diagnostic(path, DiagnosticCode.INDEX_FRONTMATTER, message)]

        try:
            loaded = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as error:
            message = f"index frontmatter is not valid YAML: {error}"
            return body, None, [OKFParserUtil._diagnostic(path, DiagnosticCode.UNPARSEABLE_FRONTMATTER, message)]

        if not isinstance(loaded, dict) or loaded.get("okf_version") is None:
            return body, None, []

        version = str(loaded["okf_version"]).strip()
        if version == OKF_VERSION:
            return body, version, []

        message = f"bundle declares okf_version {version!r}; this reader targets {OKF_VERSION!r} and reads the bundle anyway"
        return body, version, [OKFParserUtil._diagnostic(path, DiagnosticCode.VERSION_MISMATCH, message)]

    @staticmethod
    def _diagnostic(path: str, code: DiagnosticCode, message: str) -> OKFDiagnostic:
        """
        Build one diagnostic.

        :param path: Bundle-relative path the complaint concerns; ``""`` for bundle level.
        :param code: The diagnostic code.
        :param message: Human-readable detail.
        :return: The diagnostic.
        """
        return OKFDiagnostic(path=path, code=code.value, message=message)

    @staticmethod
    def _as_optional_str(value: Any) -> str | None:
        """
        Coerce a scalar frontmatter value to text, keeping ``None`` as ``None``.

        YAML resolves an unquoted timestamp to a ``datetime`` and an unquoted number to an
        ``int``/``float``, so a field the format describes as text does not always arrive as
        text. Stringifying carries the value; rejecting it would not.

        :param value: The raw frontmatter value.
        :return: The value as text, or ``None``.
        """
        if value is None or isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _as_mapping(value: Any) -> dict[str, Any]:
        """
        Coerce a frontmatter value expected to be a mapping.

        :param value: The raw frontmatter value.
        :return: The mapping, or an empty one if it is not a mapping.
        """
        return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}

    @staticmethod
    def _as_mapping_list(value: Any) -> list[dict[str, Any]]:
        """
        Coerce a frontmatter value expected to be a list of mappings.

        Entries that are not mappings are dropped: these lists carry ``{by, at}``-shaped
        records, and a scalar cannot be read as one.

        :param value: The raw frontmatter value.
        :return: The mapping entries, in order.
        """
        if not isinstance(value, list):
            return []
        return [OKFParserUtil._as_mapping(entry) for entry in value if isinstance(entry, dict)]

    @staticmethod
    def _as_verified(path: str, value: Any, diagnostics: list[OKFDiagnostic]) -> list[dict[str, Any]]:
        """
        Normalise ``verified``, which the format allows to be a bare mapping.

        Treating a bare mapping as a one-element list is a conformance MUST.

        :param path: Bundle-relative path, for the diagnostic.
        :param value: The raw frontmatter value.
        :param diagnostics: Collector appended to when a coercion happens.
        :return: The verified entries.
        """
        if isinstance(value, dict):
            message = "'verified' was a bare mapping; read as a one-element list"
            diagnostics.append(OKFParserUtil._diagnostic(path, DiagnosticCode.COERCED_SCALAR, message))
            return [OKFParserUtil._as_mapping(value)]
        return OKFParserUtil._as_mapping_list(value)

    @staticmethod
    def _as_tags(path: str, value: Any, diagnostics: list[OKFDiagnostic]) -> list[str]:
        """
        Normalise ``tags``, which is tolerated as a scalar and whose entries are stringified.

        :param path: Bundle-relative path, for the diagnostic.
        :param value: The raw frontmatter value.
        :param diagnostics: Collector appended to when a coercion happens.
        :return: The tags as text, in order.
        """
        if value is None:
            return []

        if isinstance(value, list):
            if any(not isinstance(entry, str) for entry in value):
                message = "a non-string 'tags' entry was stringified"
                diagnostics.append(OKFParserUtil._diagnostic(path, DiagnosticCode.COERCED_SCALAR, message))
            return [str(entry) for entry in value]

        message = f"'tags' was a scalar {value!r}; read as a one-element list"
        diagnostics.append(OKFParserUtil._diagnostic(path, DiagnosticCode.COERCED_SCALAR, message))
        return [str(value)]
