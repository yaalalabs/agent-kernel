"""The OKF backend: an Open Knowledge Format bundle served as a knowledge base.

``OKFManager`` joins the two axes. A :class:`DocumentStore` supplies the bytes;
:class:`OKFParserUtil` turns them into concepts; this class holds the result as one in-process
manifest and answers ``search`` / ``fetch`` / ``browse`` / ``write`` from it.

**Cost, stated plainly, because it is the design's central trade.** ``connect()`` walks the
whole store once and is called from ``__init__``, so constructing a manager over a large bundle
blocks until the walk finishes — deliberate, so a misconfigured store fails at construction
rather than inside an agent's first tool call. Thereafter every operation costs one
``time.monotonic()`` comparison, except the one call that crosses the ``refresh_seconds``
boundary, which pays a whole fresh walk. For a local bundle that is one ``os.walk`` plus one
bounded read per concept. For S3 it is one paginated listing plus **one ranged GET per
concept** — at the 10,000-concept design target and the 300 s default, 10,000 ranged GETs every
five minutes, *per pod*. Raise ``refresh_seconds`` for a large S3 bundle, or set it to ``None``
for one known to be immutable and call :meth:`reload` when it changes.

Nothing is ever filtered on trust or staleness. Both ride on every record as
``metadata["trust"]`` / ``metadata["stale"]``, because the OKF specification makes them
advisory signals rather than grounds for rejection.
"""

import importlib.metadata
import logging
import posixpath
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional
from uuid import uuid4

import yaml

from ..base import Record
from ..document import DocumentKnowledgeBase
from ..errors import KnowledgeCapabilityError, KnowledgePathError
from ..model import KnowledgeCapabilities
from ..store.base import DocumentStore
from .model import DiagnosticCode, OKFBundle, OKFConcept, OKFDiagnostic
from .parser import BODY_INDEX_MAX_BYTES, FRONTMATTER_MAX_BYTES, LOG_FILENAME, OKFParserUtil

log = logging.getLogger("ak.OKFManager")

_MARKDOWN_SUFFIX = ".md"

# Field weights for the lexical ranker. Frontmatter a curator wrote deliberately outranks body
# prose: a title match is a stronger signal than the same word appearing somewhere in a table.
_FIELD_WEIGHTS = {"title": 4, "tags": 3, "type": 2, "description": 2, "body": 1}

# Frontmatter emitted by write() in this exact order, so two writes of the same content produce
# byte-identical documents. Caller extras follow, in the order the caller supplied them.
_WRITE_KEY_ORDER = ("type", "title", "description", "tags", "status", "generated", "sources")

# `generated` and `verified` are reserved provenance metadata; allowing callers to supply them would let writers forge the producer or trust tier.
# Other unknown metadata is preserved as `extra` rather than dropped.
_WRITE_RESERVED_METADATA = frozenset({"id", "type", "title", "description", "tags", "status", "sources", "generated", "verified"})

_DEFAULT_CONCEPT_TYPE = "Note"
_SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")
_FALLBACK_SLUG = "concept"
_SLUG_MAX_LENGTH = 48


class OKFManager(DocumentKnowledgeBase):
    """
    An OKF bundle exposed through the knowledge-base contract.

    Capabilities are built per instance from the store it was handed, which is the point of the
    capability model: the same class over a read-only prefix honestly declares
    ``writable=False``. ``query`` is deliberately ``False`` — an OKF bundle has no query
    language, so ``read()`` routes to ``search()``.
    """

    def __init__(
        self,
        store: DocumentStore,
        name: str = "",
        description: Optional[str] = None,
        refresh_seconds: Optional[float] = 300.0,
        max_concepts: int = 10_000,
        producer: Optional[str] = None,
        write_prefix: str = "generated",
    ) -> None:
        """
        Open an OKF bundle held in a document store.

        :param store: Where the bundle's documents live.
        :param name: Backend name; defaults to ``"okf"`` when empty.
        :param description: Human-readable description surfaced to the agent.
        :param refresh_seconds: How stale the manifest may get before the next operation
            re-walks; ``None`` disables automatic refresh entirely.
        :param max_concepts: Ceiling on retained concepts; the walk truncates beyond it.
        :param producer: Actor stamped into ``generated.by`` on write; defaults to
            ``"agentkernel/<version>"``.
        :param write_prefix: Directory synthesised write paths are placed under.
        :return: None.
        :raises ValueError: If the resulting capability declaration is incoherent.
        """
        super().__init__(
            store=store,
            capabilities=KnowledgeCapabilities(
                kinds=["document"],
                search=True,
                search_mode="lexical",
                fetch=True,
                browse=True,
                writable=True,
                derives_schema=True,
            ),
            name=name,
        )
        self.name = name
        self.description = description or "Open Knowledge Format bundle"
        self._refresh_seconds = refresh_seconds
        self._max_concepts = max_concepts
        self._write_prefix = write_prefix
        self._producer = producer.strip() if producer and producer.strip() else self._default_producer()

        self._manifest: Optional[OKFBundle] = None
        self._loaded_at = 0.0
        # A plain threading.Lock, not an asyncio primitive: this tier is synchronous and the
        # tools KnowledgeBuilder emits are sync callables a framework may run on a thread pool.
        self._refresh_lock = threading.Lock()

        self.connect()

    @property
    def backend_name(self) -> str:
        """
        Return the name this backend is known by.

        :return: The configured name, or ``"okf"``.
        """
        return self.name if self.name else "okf"

    def connect(self, **kwargs) -> None:
        """
        Load the bundle manifest, walking the store once.

        :param kwargs: Accepted for contract compatibility; unused.
        :return: None.
        :raises Exception: Whatever the store raises. An initial load failure propagates,
            because a misconfigured store must not look like an empty bundle.
        """
        self._ensure_manifest()

    def get_description(self) -> str:
        """
        Describe the backend, surfacing bundle diagnostics rather than hiding them.

        :return: Description text, with a diagnostic summary appended when any exist.
        """
        manifest = self._ensure_manifest()
        described = f"{self.backend_name}: {self.description}"
        if not manifest.diagnostics:
            return described

        first = manifest.diagnostics[0]
        return f"{described} ({len(manifest.diagnostics)} bundle diagnostic(s); first: {first.code} at {first.path})"

    def reload(self) -> OKFBundle:
        """
        Re-walk the store immediately, regardless of the refresh interval.

        :return: The freshly built manifest.
        """
        with self._refresh_lock:
            self._manifest = self._walk()
            self._loaded_at = time.monotonic()
            return self._manifest

    def search(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        """
        Rank concepts lexically against a query.

        Scoring is field-weighted presence, not frequency: a concept scores the weight of each
        field containing a distinct query token. Frequency over a bounded body window would
        reward long preambles rather than relevance.

        :param query: Natural-language query text.
        :param limit: Maximum number of records to return.
        :param kwargs: Accepted for contract compatibility; unused.
        :return: Matching records ordered by descending score, ties broken by path.
        """
        manifest = self._ensure_manifest()
        tokens = OKFParserUtil.tokenise(query)
        if not tokens or limit <= 0:
            return []

        scored = [(self._score(concept, tokens), concept) for concept in manifest.concepts.values()]
        # Ties break on path so two processes holding the same bundle agree on the order.
        ranked = sorted(((score, concept) for score, concept in scored if score > 0), key=lambda pair: (-pair[0], pair[1].path))
        return [self._concept_record(concept) for _, concept in ranked[:limit]]

    def fetch(self, ids: List[str], **kwargs) -> List[Record]:
        """
        Return concepts by bundle path, in the order requested.

        The only operation that reads a full body, and therefore the only one whose records
        carry ``metadata["links"]`` — which is how an agent traverses the bundle graph.

        :param ids: Bundle-relative concept paths.
        :param kwargs: Accepted for contract compatibility; unused.
        :return: One record per resolvable id; unknown or unreadable ids are omitted.
        """
        self._ensure_manifest()
        records: List[Record] = []
        seen: set[str] = set()

        for raw_id in ids or []:
            concept = self._load_full_concept(raw_id)
            if concept is None or concept.path in seen:
                continue
            seen.add(concept.path)
            records.append(self._concept_record(concept, include_body=True))
        return records

    def browse(self, path: str = "", limit: int = 50, **kwargs) -> List[Record]:
        """
        Enumerate a directory of the bundle.

        A curated ``index.md`` wins at any level, not only at the bundle root, because the
        format reserves that filename everywhere. Its listing is returned whole — ``limit``
        truncates a derived listing, never a curated one.

        :param path: Bundle-relative directory; empty means the bundle root.
        :param limit: Maximum number of entries in a derived listing.
        :param kwargs: Accepted for contract compatibility; unused.
        :return: Records describing the directory's contents.
        """
        manifest = self._ensure_manifest()
        try:
            directory = DocumentStore.normalise_relative(path)
        except KnowledgePathError:
            log.warning("[%s.browse] refusing a path outside the bundle: %r", self.backend_name, path)
            return []

        index_path = manifest.index_files.get(directory)
        if index_path is not None:
            return self._index_record(index_path)
        return self._derived_listing(manifest, directory, limit)

    def write(self, records: Iterable[Record], **kwargs) -> None:
        """
        Emit conformant OKF concept documents into the bundle.

        Each write is write-through: once the bytes are durable the rendered document is parsed
        back and inserted into the live manifest, so the concept is visible to the very next
        ``fetch``/``browse``/``search`` rather than after up to ``refresh_seconds``.

        :param records: Records to persist; ``text`` becomes the body, ``metadata`` the frontmatter.
        :param kwargs: Accepted for contract compatibility; unused.
        :return: None.
        :raises KnowledgeCapabilityError: If the backend or its store is not writable.
        :raises KnowledgePathError: If a supplied id is not a writable bundle path.
        """
        if not self.capabilities.writable:
            raise KnowledgeCapabilityError(self.backend_name, "write")

        manifest = self._ensure_manifest()
        for record in records or []:
            metadata = dict(record.get("metadata", {}) or {})
            path = self._write_path(metadata)
            document = self._render_document(record.get("text", "") or "", metadata)

            self._store.write_bytes(path, document.encode("utf-8"))
            concept, diagnostics = OKFParserUtil.parse_concept(path, document, body_complete=True)
            if concept is None:
                # Unreachable for a document this class rendered, but a silent hole here would
                # mean a durable write invisible until the next walk.
                log.warning("[%s.write] wrote %s but could not parse it back: %s", self.backend_name, path, diagnostics)
                continue
            manifest.concepts[path] = concept

    def format_results(self, rows: List[Record]) -> str:
        """
        Render records so both the content and the routing signals reach the prompt.

        The base format carries text and source; OKF adds tier and staleness, the signals an
        agent needs in order to decide what to trust. Both are rendered, because the text *is*
        the answer: dropping it would leave ``fetch`` reporting metadata about a document it
        had just gone out of its way to re-read in full.

        :param rows: Records returned by a read.
        :return: One line per record, followed by the document's own lines when a fetched body
            makes the record multi-line.
        """
        if not rows:
            return "No relevant knowledge found."

        lines: List[str] = []
        for row in rows:
            metadata = row.get("metadata", {}) or {}
            record_id = metadata.get("id", "")
            label = metadata.get("title") or record_id
            header = f"- [{record_id}] {label}{self._signals(metadata)}"
            text = (row.get("text", "") or "").strip()

            if not text or text in (label, record_id):
                # A concept with no description falls back to its own title, and a directory
                # record to its own path; repeating either after the header says nothing.
                lines.append(header)
            elif "\n" in text:
                # A fetched body is a whole markdown document. Inlining or indenting it would
                # mangle its own headings and tables, so it follows the header verbatim.
                lines.append(f"{header}\n{text}")
            else:
                lines.append(f"{header}: {text}")
        return "\n".join(lines)

    @staticmethod
    def _signals(metadata: Mapping[str, Any]) -> str:
        """
        Render the routing signals riding on one record.

        Assembled from what the record actually carries rather than from a fixed template,
        because directory and index records have neither a type nor a trust tier, and an empty
        ``trust=`` reads as a lost value rather than as a record that never had one.

        :param metadata: The record's metadata.
        :return: The signal suffix, or ``""`` when the record carries no signals.
        """
        parts: List[str] = []
        if metadata.get("kind"):
            parts.append(str(metadata["kind"]))
        if metadata.get("trust"):
            parts.append(f"trust={metadata['trust']}")
        if metadata.get("stale"):
            parts.append("STALE")
        return f" — {' · '.join(parts)}" if parts else ""

    def _derived_schema(self) -> Mapping[str, Any]:
        """
        Describe the bundle from the bundle itself.

        Derivation is the whole reason OKF declares ``derives_schema``: a bundle already states
        its own version, types and layout, so transcribing them into an ``add_schema()`` call
        per deployment would only create a second thing to keep in sync.

        :return: The bundle's self-description.
        """
        manifest = self._ensure_manifest()
        return {
            "okf_version": manifest.okf_version,
            "concept_count": len(manifest.concepts),
            "types": sorted({concept.type for concept in manifest.concepts.values()}),
            "top_level_directories": sorted({path.split("/", 1)[0] for path in manifest.concepts if "/" in path}),
            "reserved_files": {"index": sorted(manifest.index_files.values()), "log": sorted(manifest.log_files)},
            "diagnostics": len(manifest.diagnostics),
            "truncated": manifest.truncated,
        }

    def _ensure_manifest(self) -> OKFBundle:
        """
        Return a manifest, refreshing it when the interval has elapsed.

        The initial load blocks, because there is nothing to serve. A refresh never blocks: a
        caller that cannot take the lock is served the current manifest, one interval stale, so
        two callers crossing the boundary together produce one walk rather than two.

        :return: The current manifest.
        """
        manifest = self._manifest
        if manifest is None:
            with self._refresh_lock:
                if self._manifest is None:
                    self._manifest = self._walk()
                    self._loaded_at = time.monotonic()
                return self._manifest

        if self._refresh_seconds is None or (time.monotonic() - self._loaded_at) < self._refresh_seconds:
            return manifest

        if self._refresh_lock.acquire(blocking=False):
            try:
                # Assigned as a whole object, so no caller ever observes a half-built manifest.
                self._manifest = self._walk()
            except Exception as error:
                # Broad by design: a transient store failure must not kill a serving pod, and
                # the previous manifest is still a correct answer, only older.
                log.warning("[%s] manifest refresh failed, serving the previous manifest: %s", self.backend_name, error)
            finally:
                # Reset even on failure, so an outage costs one attempt per interval rather
                # than one per tool call.
                self._loaded_at = time.monotonic()
                self._refresh_lock.release()
        return self._manifest

    def _walk(self) -> OKFBundle:
        """
        Read the whole store once and build a manifest from it.

        Consumes ``store.list()`` in its contractual global-lexicographic order, which is what
        makes ``max_concepts`` truncation identical across processes.

        :return: The parsed bundle.
        """
        bundle = OKFBundle()
        for path in self._store.list():
            if not path.endswith(_MARKDOWN_SUFFIX):
                continue

            if OKFParserUtil.is_reserved(path):
                self._absorb_reserved(bundle, path)
                continue

            if len(bundle.concepts) >= self._max_concepts:
                # Truncation drops concepts, not the walk: `list()` is globally lexicographic,
                # so breaking here would also abandon every reserved file sorting after the
                # cap — losing a bundle's curated root index.md to a deep `aaa/` directory.
                if not bundle.truncated:
                    bundle.truncated = True
                    message = f"bundle exceeds max_concepts={self._max_concepts}; kept the first {len(bundle.concepts)} concepts"
                    bundle.diagnostics.append(OKFDiagnostic(path="", code=DiagnosticCode.TRUNCATED.value, message=message))
                continue

            self._absorb_concept(bundle, path)

        for diagnostic in bundle.diagnostics:
            log.warning("[%s.walk] %s at %s: %s", self.backend_name, diagnostic.code, diagnostic.path or "<bundle>", diagnostic.message)
        return bundle

    def _absorb_reserved(self, bundle: OKFBundle, path: str) -> None:
        """
        Record a reserved file, which is never parsed as a concept.

        :param bundle: Manifest under construction.
        :param path: Bundle-relative path of the reserved file.
        :return: None.
        """
        if posixpath.basename(path).lower() == LOG_FILENAME:
            bundle.log_files.append(path)
            return

        directory = posixpath.dirname(path)
        data = self._read_walk_document(bundle, path, whole=True)
        if data is None:
            return

        _, okf_version, diagnostics = OKFParserUtil.parse_index(path, OKFParserUtil.decode_document(data), is_root=directory == "")
        bundle.index_files[directory] = path
        bundle.diagnostics.extend(diagnostics)
        if okf_version is not None:
            bundle.okf_version = okf_version

    def _absorb_concept(self, bundle: OKFBundle, path: str) -> None:
        """
        Parse one concept from a bounded prefix, and record it or its diagnostics.

        Only the first 24 KiB is read: frontmatter plus the body window the token index is built
        from. A document whose frontmatter runs past that window is re-read in full rather than
        skipped, because an unusually large block is not a malformed one.

        :param bundle: Manifest under construction.
        :param path: Bundle-relative path of the concept document.
        :return: None.
        """
        data = self._read_walk_document(bundle, path, whole=False)
        if data is None:
            return

        text = OKFParserUtil.decode_document(data)
        if OKFParserUtil.split_frontmatter(text)[0] is None:
            whole = self._read_walk_document(bundle, path, whole=True)
            if whole is None:
                return
            text = OKFParserUtil.decode_document(whole)

        concept, diagnostics = OKFParserUtil.parse_concept(path, text, body_complete=False)
        bundle.diagnostics.extend(diagnostics)
        if concept is not None:
            bundle.concepts[path] = concept

    def _read_walk_document(self, bundle: OKFBundle, path: str, *, whole: bool) -> Optional[bytes]:
        """
        Read a document during a walk, turning a store failure into a diagnostic.

        A single unreadable file must never abort a bundle load; the conformance rules require
        the rest of the bundle to keep working.

        :param bundle: Manifest under construction, collecting any diagnostic.
        :param path: Bundle-relative path.
        :param whole: Read the whole document rather than the bounded prefix.
        :return: The bytes, or ``None`` when the file could not be read.
        """
        try:
            if whole:
                return self._store.read_bytes(path)
            return self._store.read_prefix_bytes(path, FRONTMATTER_MAX_BYTES + BODY_INDEX_MAX_BYTES)
        except FileNotFoundError as error:
            bundle.diagnostics.append(OKFDiagnostic(path=path, code=DiagnosticCode.UNREADABLE.value, message=f"document disappeared: {error}"))
        except KnowledgePathError as error:
            bundle.diagnostics.append(OKFDiagnostic(path=path, code=DiagnosticCode.PATH_ESCAPE.value, message=str(error)))
        return None

    def _score(self, concept: OKFConcept, tokens: set[str]) -> int:
        """
        Score one concept against a tokenised query.

        :param concept: Concept to score.
        :param tokens: Distinct query tokens.
        :return: Sum of the weights of the fields containing each token.
        """
        fields = {
            "title": OKFParserUtil.tokenise(concept.title or ""),
            "tags": OKFParserUtil.tokenise(" ".join(concept.tags)),
            "type": OKFParserUtil.tokenise(concept.type),
            "description": OKFParserUtil.tokenise(concept.description or ""),
            "body": concept.body_tokens,
        }
        return sum(weight for field, weight in _FIELD_WEIGHTS.items() for token in tokens if token in fields[field])

    def _load_full_concept(self, raw_id: str) -> Optional[OKFConcept]:
        """
        Re-read and re-parse one concept with a complete body.

        :param raw_id: Bundle path as the caller supplied it.
        :return: The concept, or ``None`` when the id is unusable, unknown or unreadable.
        """
        try:
            path = DocumentStore.normalise_relative(raw_id or "")
        except KnowledgePathError:
            log.warning("[%s.fetch] refusing an id outside the bundle: %r", self.backend_name, raw_id)
            return None

        if not path:
            return None

        data = self._read_document(path)
        if data is None:
            return None

        concept, _ = OKFParserUtil.parse_concept(path, OKFParserUtil.decode_document(data), body_complete=True)
        if concept is None:
            log.warning("[%s.fetch] document at %s is not a usable concept", self.backend_name, path)
        return concept

    def _index_record(self, index_path: str) -> List[Record]:
        """
        Serve a curated listing from a directory's ``index.md``.

        :param index_path: Bundle-relative path of the index file.
        :return: A one-record listing, or an empty list when the index cannot be read.
        """
        data = self._read_document(index_path)
        if data is None:
            return []

        is_root = posixpath.dirname(index_path) == ""
        body, _, _ = OKFParserUtil.parse_index(index_path, OKFParserUtil.decode_document(data), is_root=is_root)
        return [{"text": body, "metadata": {"id": index_path, "source": index_path, "title": index_path, "kind": "index"}}]

    def _derived_listing(self, manifest: OKFBundle, directory: str, limit: int) -> List[Record]:
        """
        Derive a directory listing from the manifest when no index curates one.

        The store cannot help: its ``list`` is recursive and emits files only, so immediate
        subdirectories are inferred from the concept paths already held.

        :param manifest: The loaded manifest.
        :param directory: Normalised bundle-relative directory.
        :param limit: Maximum number of entries.
        :return: Child records in lexicographic order.
        """
        prefix = f"{directory}/" if directory else ""
        concepts: List[OKFConcept] = []
        subdirectories: set[str] = set()

        for path, concept in manifest.concepts.items():
            if not path.startswith(prefix):
                continue
            remainder = path[len(prefix) :]
            head, separator, _ = remainder.partition("/")
            if separator:
                subdirectories.add(head)
            else:
                concepts.append(concept)

        if not concepts and not subdirectories and directory:
            log.warning("[%s.browse] no such directory in the bundle: %r", self.backend_name, directory)
            return []

        entries: List[Record] = [self._directory_record(prefix, name) for name in sorted(subdirectories)]
        entries.extend(self._concept_record(concept) for concept in sorted(concepts, key=lambda item: item.path))
        return entries[:limit] if limit > 0 else []

    @staticmethod
    def _directory_record(prefix: str, name: str) -> Record:
        """
        Build the record standing for a subdirectory.

        :param prefix: Parent directory prefix, ``""`` at the bundle root.
        :param name: Immediate subdirectory name.
        :return: A directory record whose id ends in ``/`` so it reads as a namespace.
        """
        path = f"{prefix}{name}/"
        return {"text": path, "metadata": {"id": path, "source": path, "title": name, "kind": "directory"}}

    @staticmethod
    def _concept_record(concept: OKFConcept, include_body: bool = False) -> Record:
        """
        Shape one concept as a record.

        :param concept: The concept.
        :param include_body: Carry the full body and its links, which only ``fetch`` has read.
        :return: The record.
        """
        metadata: dict[str, Any] = {
            "id": concept.path,
            "source": concept.path,
            "title": concept.title or concept.path,
            "kind": concept.type,
            "trust": concept.trust.value,
            "stale": concept.stale,
        }
        if include_body:
            metadata["links"] = list(concept.links)
            return {"text": concept.body or "", "metadata": metadata}
        return {"text": concept.description or concept.title or concept.path, "metadata": metadata}

    def _write_path(self, metadata: dict) -> str:
        """
        Decide where a written record lands.

        A supplied id is honoured; otherwise one is synthesised, because the ``write_kb`` tool
        signature carries no id and an agent would otherwise have no way to name a bundle path.
        Either way the result is comma-free, so every id this backend hands out round-trips
        through the fetch tool's comma-separated id list, and it ends in ``.md``, so the next
        walk still recognises it — a suffix-less path would write, serve through the
        write-through, then silently vanish from the manifest one refresh later.

        :param metadata: The record's metadata.
        :return: Bundle-relative path to write.
        :raises KnowledgePathError: If a supplied id escapes the bundle, contains a ``,``,
            resolves to the bundle root, or names a reserved OKF file.
        """
        supplied = metadata.get("id")
        if isinstance(supplied, str) and supplied.strip():
            path = DocumentStore.normalise_relative(supplied)
            if not path:
                raise KnowledgePathError(f"concept path may not be the bundle root: {supplied!r}")
            if "," in path:
                raise KnowledgePathError(f"concept path may not contain ',': {supplied!r}")
            if not path.endswith(_MARKDOWN_SUFFIX):
                path = f"{path}{_MARKDOWN_SUFFIX}"
            # Refused rather than renamed: index.md and log.md are the bundle's own structure,
            # and a write landing on one would overwrite a curated listing with a concept the
            # walk then declines to read back.
            if OKFParserUtil.is_reserved(path):
                raise KnowledgePathError(f"concept path may not name a reserved OKF file: {supplied!r}")
            return path

        slug = self._slug(metadata.get("title") or metadata.get("type") or _FALLBACK_SLUG)
        return f"{self._write_prefix}/{slug}-{uuid4().hex[:8]}{_MARKDOWN_SUFFIX}"

    def _render_document(self, text: str, metadata: dict) -> str:
        """
        Render one record as a conformant OKF concept document.

        Key order is fixed rather than sorted, so re-writing the same content twice produces
        byte-identical output and a bundle under version control stays reviewable.

        :param text: Body text.
        :param metadata: Record metadata supplying the frontmatter.
        :return: The complete document.
        """
        concept_type = metadata.get("type")
        frontmatter: dict[str, Any] = {
            "type": concept_type if isinstance(concept_type, str) and concept_type.strip() else _DEFAULT_CONCEPT_TYPE,
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "tags": metadata.get("tags"),
            "status": metadata.get("status"),
            "generated": {"by": self._producer, "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()},
            "sources": metadata.get("sources"),
        }
        ordered = {key: frontmatter[key] for key in _WRITE_KEY_ORDER if frontmatter[key] is not None}
        ordered.update({key: value for key, value in metadata.items() if key not in _WRITE_RESERVED_METADATA})

        rendered = yaml.safe_dump(ordered, sort_keys=False, default_flow_style=False, allow_unicode=True)
        return f"---\n{rendered}---\n\n{text}"

    @staticmethod
    def _slug(value: str) -> str:
        """
        Reduce a title or type to a comma-free filename slug.

        :param value: Text to slugify.
        :return: A ``[a-z0-9-]`` slug, never empty.
        """
        slug = _SLUG_SEPARATOR.sub("-", str(value).lower()).strip("-")
        return slug[:_SLUG_MAX_LENGTH] or _FALLBACK_SLUG

    @staticmethod
    def _default_producer() -> str:
        """
        Resolve the actor string stamped into ``generated.by``.

        :return: ``"agentkernel/<version>"``, or ``"agentkernel/unknown"`` when the package is
            imported from a source tree with no distribution metadata.
        """
        try:
            return f"agentkernel/{importlib.metadata.version('agentkernel')}"
        except importlib.metadata.PackageNotFoundError:
            return "agentkernel/unknown"
