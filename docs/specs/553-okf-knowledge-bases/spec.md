# #553: Open Knowledge Format support and the knowledge-base architecture refactor — Implementation Spec

Details how the approved [`design.md`](design.md) is built. The knowledge-base tier is split along the
three axes the design fixes — representation (`knowledgebase/okf/`), capability
(`KnowledgeCapabilities` + the five-operation set on `KnowledgeBase`), and storage
(`knowledgebase/store/`) — and Open Knowledge Format lands as `OKFManager`, a `DocumentKnowledgeBase`
composing an OKF parser with a `DocumentStore`. `design.md` is the requirements source; every
requirement there is traced into a section below. Sections that resolve something the design
deliberately left to this stage, or that add a component the design does not name, are marked
**[spec-level decision]** and collected in [Deviations and additions](#deviations-and-additions) for
design re-review.

Nothing in `ak-py/src` outside `agentkernel/knowledgebase/` imports the package (verified by grep over
`ak-py/src` and `e2e`), so the blast radius is the package itself, the four examples under
`examples/cli/knowledgebase/openai/`, three docs pages, and two dev skills.

## Verification gate — decision 8, closed

`design.md` decision 8 makes re-checking every `[SPEC]`-marked claim in
[`research/okf-format-survey.md`](research/okf-format-survey.md) against the OKF **v0.2**
specification text a precondition for this document. That re-check was performed against
`okf/SPEC.md` in `GoogleCloudPlatform/knowledge-catalog` on 2026-09-01 and the survey's verification
block now records it. Three outcomes bear on the conformance behavior fixed below:

1. **Corrected**: surfacing a failing attestation is a **SHOULD**, not a MUST. The design never relied
   on the stronger reading (it reads Attested Computation concepts like any other concept), so no
   requirement changes — but `OKFManager` must not *drop* a failed attestation either, which it does
   not: `verified` and the computation family are carried through as data.
2. **Tightened**: reserved filenames are reserved **at any level** of the tree, and an `index.md` may
   carry frontmatter **only** for `okf_version` **at the bundle root**. This is load-bearing for
   `browse()` and for the walk — see [`index.md` handling](#indexmd-and-logmd-handling).
3. **Clarified**: the v0.1 → v0.2 fallbacks are **MAY** (`timestamp`) and **SHOULD read `sources` /
   MAY parse legacy `# Citations`**. Declining both — design decision 5, v0.2 only — is therefore a
   conformant choice, not a deviation. The spec asserts this by test rather than leaving it as prose.

## Design

### Package layout

```
ak-py/src/agentkernel/knowledgebase/
├── __init__.py           # REWRITTEN: lazy PEP 562 exports
├── model.py              # NEW: KnowledgeCapabilities, KnowledgeMetadata, KnowledgeRecord
├── errors.py             # NEW: KnowledgeError, KnowledgeCapabilityError, KnowledgePathError
├── base.py               # CHANGED: capability-aware ABC, concrete read(), schema derivation
├── document.py           # NEW: DocumentKnowledgeBase
├── knowledgebuilder.py   # CHANGED: capability-gated tools, generic write metadata
├── chroma.py             # CHANGED: read -> search, declares capabilities
├── neo4j.py              # CHANGED: read -> query, generic write metadata, declares capabilities
├── starburst.py          # CHANGED: schema -> db_schema, read -> query, declares capabilities
├── store/
│   ├── __init__.py       # NEW: lazy exports (keeps boto3 optional)
│   ├── base.py           # NEW: DocumentStore ABC, from_uri, path normalisation
│   ├── local.py          # NEW: LocalDocumentStore (stdlib only)
│   └── s3.py             # NEW: S3DocumentStore (existing `aws` extra)
└── okf/
    ├── __init__.py       # NEW: lazy exports
    ├── model.py          # NEW: OKFConcept, OKFBundle, OKFDiagnostic, TrustTier
    ├── parser.py         # NEW: bytes/str -> OKFConcept; links, trust, staleness
    └── manager.py        # NEW: OKFManager
```

Rules governing the package, each stated so a reviewer can check it mechanically:

1. **`okf/` never touches a `DocumentStore` or the network.** `parser.py` takes `bytes`/`str` and a
   path string, and returns objects. Asserted by a test that imports `agentkernel.knowledgebase.okf`
   and fails if `agentkernel.knowledgebase.store` appears in `sys.modules` on its account.
2. **`store/` never knows markdown, YAML, or OKF.** No import of `yaml` or of `okf/` anywhere under
   `store/`.
3. **Stores take explicit constructor parameters and never read `AKConfig`** — the shared-driver and
   transport rule. `from_uri` is a string parser, not a config reader.
4. **The contract suites import `pytest`** and therefore live outside the package's lazy export map.
   *As built* they live in `ak-py/tests/knowledgebase_contracts.py` rather than a
   `knowledgebase/testing.py`, because unlike `sandbox/testing.py` they are not intended as a
   published helper for out-of-tree backend authors.

### `knowledgebase/model.py` — capability declaration and record typing

```python
class KnowledgeCapabilities(BaseModel):
    """What a backend actually supports; undeclared operations raise KnowledgeCapabilityError."""

    kinds: list[str] = Field(default_factory=list)        # open taxonomy: vector|structured|graph|document|…
    search: bool = False                                   # relevance retrieval
    search_mode: Literal["semantic", "lexical"] | None = None
    query: bool = False                                    # query-language retrieval
    query_language: str | None = None                      # e.g. "cypher", "sql"
    fetch: bool = False                                    # retrieval by identity
    browse: bool = False                                   # namespace enumeration
    writable: bool = False
    derives_schema: bool = False                           # schema() self-describes without add_schema()
```

- **The model carries no cross-field validator** — both invariants are enforced in
  `KnowledgeBase.__init__`, because the design requires each `ValueError` to *name the backend* and the
  capabilities object does not know it. An application can therefore build a `KnowledgeCapabilities`
  for inspection without owning a backend. **[spec-level decision]**
- **`search_mode` is deliberately *not* bidirectional with `search`**, unlike `query_language`/`query`.
  The design declares exactly two invariants and nothing routes on `search_mode` — it is advisory
  metadata reaching the agent through `schema()`. `search=True, search_mode=None` is legal and means
  "relevance retrieval, kind unstated". Recorded here so the asymmetry reads as considered.
- Two `TypedDict`s (`total=False`), documentation-only, never validated at runtime:

```python
class KnowledgeMetadata(TypedDict, total=False):
    id: str          # backend-native identity; REQUIRED in metadata when capabilities.fetch is True
    source: str
    title: str
    kind: str
    trust: str
    stale: bool
    links: list[str]

class KnowledgeRecord(TypedDict, total=False):
    text: str
    metadata: KnowledgeMetadata
```

`Record = Mapping[str, Any]` stays the annotation on every signature; neither `TypedDict` appears in
one. The `id` rule is enforced by `KnowledgeBaseContract`, not by runtime validation.

### `knowledgebase/errors.py`

```python
class KnowledgeError(Exception): ...

class KnowledgeCapabilityError(KnowledgeError):
    """An operation the backend does not declare in its KnowledgeCapabilities."""
    def __init__(self, *args: str) -> None: ...   # (subject, operation) or (operation,)

class KnowledgePathError(KnowledgeError):
    """A path escaped the store's namespace, or is otherwise unusable as an identity."""
```

- `KnowledgeCapabilityError` mirrors `SandboxCapabilityError` (`sandbox/errors.py:20-39`) exactly,
  including the message `"{subject} does not support capability: {operation}"` and the
  `subject`/`capability` attributes. It does **not** subclass `NotImplementedError` (design item 2).
- `KnowledgePathError` is an **addition** the design does not name: the design says the store refuses
  an escaping path and `DocumentKnowledgeBase` maps the refusal to an agent-facing error result. That
  mapping needs a type to catch, and catching `ValueError` would also swallow unrelated failures.
  **[spec-level decision]** — see [Deviations and additions](#deviations-and-additions) A.

### `knowledgebase/base.py` — the reshaped ABC

```python
class KnowledgeBase(ABC):
    capabilities: KnowledgeCapabilities          # bare annotation, no class-level default

    def __init__(self, capabilities: KnowledgeCapabilities, name: str | None = None) -> None:
        self._dynamic_schema: dict[str, Any] = {}
        self.capabilities = capabilities
        validate_capabilities(capabilities, name or type(self).__name__)

    # unchanged abstract surface
    @property
    @abstractmethod
    def backend_name(self) -> str: ...
    @abstractmethod
    def connect(self, **kwargs) -> None: ...
    @abstractmethod
    def get_description(self) -> str: ...

    # the five operations — all concrete, all optional
    def search(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        raise KnowledgeCapabilityError(self.backend_name, "search")
    def query(self, statement: str, limit: int = 3, **kwargs) -> List[Record]:
        raise KnowledgeCapabilityError(self.backend_name, "query")
    def fetch(self, ids: List[str], **kwargs) -> List[Record]:
        raise KnowledgeCapabilityError(self.backend_name, "fetch")
    def browse(self, path: str = "", limit: int = 50, **kwargs) -> List[Record]:
        raise KnowledgeCapabilityError(self.backend_name, "browse")
    def write(self, records: Iterable[Record], **kwargs) -> None:
        raise KnowledgeCapabilityError(self.backend_name, "write")

    # the routing rule — the design's single statement of it
    def read(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        if self.capabilities.query:
            return self.query(query, limit=limit, **kwargs)
        return self.search(query, limit=limit, **kwargs)
```

- `read` and `write` **stop being abstract**. A subclass that implements them keeps working unchanged;
  a new subclass may omit both. `connect`, `backend_name`, and `get_description` stay abstract, so the
  required surface shrinks from five members to three.
- The default operations raise with `self.backend_name`, which is safe: by the time an operation is
  called the subclass is fully constructed. Only the **construction-time** validation is forbidden from
  reading the property.
- `validate_capabilities(capabilities, subject) -> None` is a module-level function, not a private
  method, so `KnowledgeBaseContract` can exercise it directly without constructing a backend:

```python
def validate_capabilities(capabilities: KnowledgeCapabilities, subject: str) -> None:
    if not (capabilities.search or capabilities.query or capabilities.fetch
            or capabilities.browse or capabilities.writable):
        raise ValueError(f"Knowledge backend '{subject}' declares no capability: at least one of "
                         "search, query, fetch, browse, writable must be True.")
    if capabilities.query and not (capabilities.query_language or "").strip():
        raise ValueError(f"Knowledge backend '{subject}' declares query=True without a query_language.")
    if not capabilities.query and (capabilities.query_language or "").strip():
        raise ValueError(f"Knowledge backend '{subject}' declares query_language "
                         f"{capabilities.query_language!r} without query=True.")
```

Both invariants raise `ValueError` naming the backend, and the reachability check runs first so a
capability-free backend reports the more fundamental problem.

#### Schema derivation

```python
def _derived_schema(self) -> Mapping[str, Any]:
    return {}

def schema(self) -> Mapping[str, Any]:
    derived = dict(self._derived_schema())
    if not self._dynamic_schema and not derived:
        raise ValueError(f"Schema for '{self.backend_name}' has not been set! "
                         "Call .add_schema() before passing to the Agent.")
    final: dict[str, Any] = {"backend": self.backend_name}
    final.update(derived)
    final.update(self._dynamic_schema)
    final["capabilities"] = self.capabilities.model_dump()
    return final
```

- The `ValueError` message is **byte-identical** to today's (`base.py:57-58`), so any deployment
  matching on it is unaffected.
- Precedence: `backend` first and therefore overridable by `add_schema()` — today's behavior,
  preserved. `capabilities` is written **last and is not overridable**, because it is the
  machine-readable declaration the tools route on and a deployment must not be able to contradict it
  through `add_schema()`. The design says only "also add `capabilities`" and leaves precedence open.
  **[spec-level decision]**
- Neither `backend` nor `capabilities` counts as content for the emptiness guard, which is why the
  guard is evaluated before they are added.
- `capabilities.derives_schema` is a declaration, not the gate: `KnowledgeBaseContract` fails a backend
  declaring it while `_derived_schema()` returns `{}`.

#### `format_results`

```python
def format_results(self, rows: List[Record]) -> str:
    if not rows:
        return "No relevant knowledge found."
    lines = []
    for row in rows:
        metadata = row.get("metadata", {}) or {}
        text, source = row.get("text", ""), metadata.get("source", "N/A")
        record_id = metadata.get("id")
        if self.capabilities.fetch and isinstance(record_id, str) and record_id:
            lines.append(f"- [{record_id}] {text} (source: {source})")
        else:
            lines.append(f"- {text} (source: {source})")
    return "\n".join(lines)
```

The unprefixed branch is byte-for-byte `base.py:103`. A missing, empty, or non-string `id` on a
`fetch`-capable backend degrades to it rather than rendering `[None]`.

### `knowledgebase/store/` — the storage axis

```python
class DocumentStore(ABC):
    @property
    @abstractmethod
    def writable(self) -> bool: ...
    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...          # FileNotFoundError when absent
    @abstractmethod
    def exists(self, path: str) -> bool: ...
    @abstractmethod
    def list(self, prefix: str = "") -> list[str]: ...     # lexicographic, bundle-relative
    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None: ...
    def read_prefix_bytes(self, path: str, max_bytes: int) -> bytes:
        return self.read_bytes(path)[:max_bytes]           # overridable; S3 uses a ranged GET
    def close(self) -> None: ...
    @staticmethod
    def from_uri(uri: str, **kwargs) -> "DocumentStore": ...
```

- **`read_prefix_bytes` is an addition** to the design's five-method contract, with a default that
  makes it invisible to a bring-your-own store. It exists so the eager frontmatter pass is affordable
  over S3 — see [Manifest: what is retained](#manifest-what-is-retained-and-what-it-costs).
  **[spec-level decision]** — [Deviations and additions](#deviations-and-additions) C.
- **Containment is the store's obligation** and is implemented once, in `store/base.py`:

```python
def normalise_relative(path: str) -> str:
    """Bundle-relative, POSIX, containment-checked. Raises KnowledgePathError on an escape."""
    candidate = (path or "").strip().replace("\\", "/")
    if candidate.startswith("/"):
        raise KnowledgePathError(f"absolute path is not addressable in a document store: {path!r}")
    normalised = posixpath.normpath(candidate)
    if normalised in (".", ""):
        return ""
    if normalised == ".." or normalised.startswith("../"):
        raise KnowledgePathError(f"path escapes the store namespace: {path!r}")
    return normalised
```

  Every entrypoint (`read_bytes`, `read_prefix_bytes`, `exists`, `write_bytes`, `list`'s prefix) calls
  it first, and every path `list()` *emits* is produced by it — so containment covers paths no agent
  supplied: the manifest walk and links read out of a concept.
- `write_bytes` on a store declaring `writable=False` raises
  `KnowledgeCapabilityError(type(self).__name__, "write_bytes")`, before any I/O.

#### `LocalDocumentStore(root: str, writable: bool | None = None)`

- Stdlib only; no extra.
- `__init__` resolves `self._root = os.path.realpath(root)` and raises `ValueError` if it is not an
  existing directory — matching `StarburstManager.connect`'s missing-config behavior
  (`starburst.py:102`).
- `writable=None` probes `os.access(self._root, os.W_OK)`; an explicit `True`/`False` wins. Probing is
  right here and wrong for S3, where a permission cannot be read without attempting a write.
  **[spec-level decision]**
- **Traversal-time containment**, in addition to access-time: `list()` walks with `os.walk(root,
  followlinks=False)`, and for each candidate file compares
  `os.path.commonpath([self._root, os.path.realpath(full_path)]) == self._root`; a symlink resolving
  outside `root` is **skipped** by the walk and **refused** (`KnowledgePathError`) on direct read.
- `list()` collects every match and returns `sorted(matches)`. It does not rely on `os.walk`'s
  per-directory ordering, which is not globally lexicographic (`a/z.md` vs `ab/b.md`), and global
  lexicographic order is what makes `max_concepts` truncation identical across pods.
- `read_bytes` on a missing file propagates the stdlib `FileNotFoundError`.

#### `S3DocumentStore(bucket, prefix="", region=None, client=None, writable=True)`

- Requires the existing `aws` extra (`boto3>=1.41.4`, `pyproject.toml:59`); **no new extra**. The
  import is wrapped in `require_extra("aws", "s3:// document store")` (`core/util/factory.py:50`), so a
  missing `boto3` is an `ImportError` naming the extra.
- `client` injection is the test seam; otherwise `boto3.client("s3", region_name=region)`.
- `list()` pages `list_objects_v2` with `Prefix=self._key(prefix)` and concatenates pages in order —
  S3 already lists in UTF-8 binary order, and the result is `sorted()` anyway so the two orders cannot
  diverge for keys that differ only in case-folding assumptions.
- `read_bytes` maps `ClientError` with code `NoSuchKey` (and `404`) to `FileNotFoundError`, so the
  layer above sees one exception type regardless of store. Every other `ClientError` propagates.
- `read_prefix_bytes` issues `get_object(..., Range=f"bytes=0-{max_bytes - 1}")` and maps
  `InvalidRange` on a shorter object to a full `read_bytes`.
- `writable` is a **declared** constructor flag defaulting to `True`; the store never probes the bucket
  policy. An application serving a read-only prefix passes `writable=False`, and `OKFManager` folds
  that into `capabilities.writable` — the design's stated reason capabilities are per instance.

#### `DocumentStore.from_uri`

| Input | Resolves to |
|---|---|
| `s3://bucket/prefix` | `S3DocumentStore(bucket, prefix, **kwargs)` |
| `file:///abs/path` | `LocalDocumentStore("/abs/path", **kwargs)` |
| bare path (`./bundle`, `/srv/kb`) | `LocalDocumentStore(path, **kwargs)` |
| `python:pkg.mod.ClassName` | `resolve_dotted(rest, base=DocumentStore, error=AKConfigError)(**kwargs)` |
| any other `scheme://` | `AKConfigError` |

"Any other scheme" is detected with `re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", uri)` — a bare Windows-ish
path or a relative path never trips it. The `python:` discriminator is mandatory because a dotted path
*is* a valid bare path; without it, `mypkg.stores.GitStore` would silently become a
`LocalDocumentStore` rooted at a non-existent directory.

### `knowledgebase/okf/` — the representation axis

#### `okf/model.py`

```python
class TrustTier(str, Enum):
    UNVERIFIED = "unverified"
    MACHINE_CONFIRMED = "machine-confirmed"
    HUMAN_REVIEWED = "human-reviewed"

class OKFDiagnostic(BaseModel):
    path: str          # "" for bundle-level diagnostics
    code: str          # see the table below
    message: str

class OKFConcept(BaseModel):
    path: str                                   # identity; bundle-relative, POSIX
    type: str                                   # the only required frontmatter key
    title: str | None = None
    description: str | None = None
    resource: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str | None = None                   # draft | stable | deprecated (open)
    stale_after: str | None = None              # verbatim frontmatter value
    generated: dict[str, Any] = Field(default_factory=dict)
    verified: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    computation: dict[str, Any] = Field(default_factory=dict)   # runtime/parameters/computation/executor/attester
    extra: dict[str, Any] = Field(default_factory=dict)          # every unrecognised frontmatter key
    trust: TrustTier = TrustTier.UNVERIFIED     # derived
    stale: bool = False                          # derived
    body: str | None = None                      # None when only a bounded prefix was scanned
    body_tokens: set[str] = Field(default_factory=set)
    links: list[str] = Field(default_factory=list)   # populated only when body is complete

class OKFBundle(BaseModel):
    concepts: dict[str, OKFConcept] = Field(default_factory=dict)
    index_files: dict[str, str] = Field(default_factory=dict)   # directory ("" = root) -> index.md path
    log_files: list[str] = Field(default_factory=list)
    okf_version: str | None = None
    diagnostics: list[OKFDiagnostic] = Field(default_factory=list)
    truncated: bool = False
```

- `status` stays an open `str`, not an enum: the conformance rules forbid rejecting an unknown value,
  and an enum would force either a rejection or a silent coercion.
- `tags` accepts a scalar and normalises to a one-element list, the same tolerance the spec mandates
  for `verified`. A non-string scalar is stringified, with a diagnostic.

Diagnostic codes, exhaustively:

| Code | Raised when |
|---|---|
| `unparseable_frontmatter` | no frontmatter block, or `yaml.safe_load` raises / returns a non-mapping |
| `missing_type` | `type` absent, not a string, or empty after `strip()` |
| `comma_in_path` | a concept path contains `,` (it could never round-trip through `fetch_kb`) |
| `path_escape` | a link or listed path escapes the bundle namespace |
| `version_mismatch` | bundle-root `okf_version` is present and is not `"0.2"` |
| `index_frontmatter` | an `index.md` outside the bundle root carries a frontmatter block |
| `unparseable_stale_after` | `stale_after` is not an ISO-8601 timestamp |
| `coerced_scalar` | a bare `verified` mapping or a scalar `tags` value was normalised |
| `truncated` | the walk stopped at `max_concepts` |
| `unreadable` | the store raised while reading a candidate file |

#### `okf/parser.py`

```python
FRONTMATTER_MAX_BYTES = 16 * 1024
BODY_INDEX_MAX_BYTES = 8 * 1024

def split_frontmatter(data: str) -> tuple[str | None, str]: ...
def parse_concept(path: str, data: str, *, body_complete: bool) -> tuple[OKFConcept | None, list[OKFDiagnostic]]: ...
def extract_links(concept_path: str, body: str) -> tuple[list[str], list[OKFDiagnostic]]: ...
def derive_trust(verified: list[dict[str, Any]]) -> TrustTier: ...
def is_stale(stale_after: str | None, now: datetime) -> tuple[bool, list[OKFDiagnostic]]: ...
```

- **Frontmatter delimiters**: the document must open with `---` on its own first line; the block ends at
  the next line that is exactly `---`. No closing delimiter → `unparseable_frontmatter`, concept
  skipped. `yaml.safe_load` only — never `yaml.load`. `pyyaml>=6.0.2` is a **core** dependency
  (`pyproject.toml:19`), so a local-filesystem OKF backend needs no optional extra at all.
- **Tolerance, per the conformance rules** (all asserted by test):
  - unknown frontmatter keys → `extra`, untouched;
  - unknown `type` values → kept verbatim;
  - missing optional fields → defaults, no diagnostic;
  - a bare `verified` mapping → one-element list (`coerced_scalar`);
  - a broken link → kept in `links`, never resolved against the store at parse time;
  - a v0.1 `timestamp` key → `extra["timestamp"]`, **never** mapped onto `generated`; a body
    `# Citations` list → ordinary body text, **never** mapped onto `sources`. Conformant because both
    fallbacks are MAY (verification gate outcome 3).
- **Trust** derives only from `verified`: empty → `UNVERIFIED`; any entry whose `by` starts with
  `human:` → `HUMAN_REVIEWED`; otherwise `MACHINE_CONFIRMED`. Nothing else feeds it.
- **Staleness** derives only from `stale_after`, parsed with `datetime.fromisoformat` (accepting a
  trailing `Z` by substitution), compared against an injected `now` so tests are deterministic. A naive
  timestamp is read as UTC. Unparseable → `stale=False` plus `unparseable_stale_after`.
- **Nothing is ever filtered on trust or staleness.** They ride on every returned record as
  `metadata["trust"]` / `metadata["stale"]`. Asserted by a test that registers a bundle whose every
  concept is stale and unverified and checks `search`/`browse`/`fetch` still return them all.
- **Links**: `re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", body)`. A target is kept when it has no URL
  scheme and ends in `.md`; `/x/y.md` resolves bundle-absolute to `x/y.md`, `./y.md` and `../y.md`
  resolve against `posixpath.dirname(concept_path)`. An escape is dropped with `path_escape`.
  Absolute-URL targets are ignored here and never dereferenced anywhere in the layer.
- **No network fetch of reference fields.** `resource`, `sources[].resource`, and `computation` are
  carried as data. Asserted by a test that fails if the parser or manager touches `urllib`/`httpx`.

#### `index.md` and `log.md` handling

Driven by verification-gate outcome 2:

- Both names are reserved **at every directory level** and are never parsed as concepts.
- `index.md` at the **bundle root** may carry a frontmatter block, and `okf_version` is the only key
  read from it; other keys there are ignored with no diagnostic (the spec permits only this one key, so
  anything else is unrecognised content, which tolerance says to carry, not reject).
- An `index.md` **outside** the root carrying a frontmatter block gets an `index_frontmatter`
  diagnostic and its body is still used as the curated listing — carried, not rejected.
- `log.md` is recorded in `log_files` and otherwise untouched.

### `knowledgebase/document.py` — `DocumentKnowledgeBase`

The only new intermediate base class. It holds the store, folds `store.writable` into the capabilities
it was handed, and owns the two error mappings so `OKFManager` (and any second document-shaped
backend) does not repeat them:

```python
class DocumentKnowledgeBase(KnowledgeBase, ABC):
    def __init__(self, store: DocumentStore, capabilities: KnowledgeCapabilities, name: str | None = None) -> None:
        self._store = store
        capabilities = capabilities.model_copy(update={"writable": capabilities.writable and store.writable})
        super().__init__(capabilities=capabilities, name=name)

    @property
    def store(self) -> DocumentStore: ...

    def _read_document(self, path: str) -> bytes | None:
        """None on a missing document; KnowledgePathError propagates to the operation boundary."""
        try:
            return self._store.read_bytes(path)
        except FileNotFoundError:
            log.warning("[%s] document not found: %s", self.backend_name, path)
            return None
```

- Folding uses `and`, so a store that cannot write always wins over a declared `writable=True`; the
  reverse (a writable store, a backend that chooses not to write) also holds.
- `KnowledgePathError` is **not** swallowed here: each of `fetch`/`browse`/`write` catches it at its own
  boundary and returns/raises per the design ("`DocumentKnowledgeBase` turns the refusal into an error
  result for the agent"), which in practice means the operation drops that path with a logged warning
  and continues with the rest. Containment is still enforced in the store, which is the only place an
  escape is *detected*.
- `close()` delegates to `store.close()`.

### `knowledgebase/okf/manager.py` — `OKFManager`

```python
OKFManager(
    store: DocumentStore,
    name: str = "",
    description: str | None = None,
    refresh_seconds: float | None = 300.0,
    max_concepts: int = 10_000,
    producer: str | None = None,
    write_prefix: str = "generated",
)
```

Capabilities built in `__init__` from what it was given:
`kinds=["document"], search=True, search_mode="lexical", query=False, query_language=None, fetch=True,
browse=True, writable=store.writable, derives_schema=True`. `query=False` is what makes `read()` route
to `search()` under the base's rule, and is why `search_kb` is not emitted on OKF's account.

#### Manifest: what is retained, and what it costs

`connect()` walks the store once and holds one `OKFBundle` in process. Per concept the manifest retains
the parsed frontmatter, the derived trust/staleness, and a **bounded body token set** — not the body
text:

- The walk reads `store.read_prefix_bytes(path, FRONTMATTER_MAX_BYTES + BODY_INDEX_MAX_BYTES)`
  (24 KiB by default). If no closing `---` is found within it, the walk falls back to a full
  `read_bytes` for that one file, because a concept whose frontmatter exceeds 16 KiB is unusual but
  must not be skipped.
- `body_tokens` is built from the body bytes inside that window; `body` and `links` are left `None`/
  empty, and `body_complete=False` is recorded.
- **`fetch` is the only operation that reads a full body.** It re-reads the document, re-parses with
  `body_complete=True`, and therefore is the only operation whose records carry `metadata["links"]` —
  which is exactly how the design describes graph traversal ("attached as `metadata["links"]`, so an
  agent can traverse the graph with `fetch`").

This refines the design's "frontmatter is parsed eagerly … bodies are read lazily": a lexical ranker
cannot rank over bodies it never reads, so what is retained is a bounded token index of the body head
rather than the body. **[spec-level decision]** — [Deviations and additions](#deviations-and-additions) F.

**Per-operation cost, stated:** every `search`/`fetch`/`browse`/`schema`/`get_description` call runs
`_ensure_manifest()`, whose steady-state cost is one `time.monotonic()` comparison. The call that
crosses the `refresh_seconds` boundary pays the whole walk: for a local bundle, one `os.walk` plus one
bounded read per concept; for S3, one `list_objects_v2` pagination plus **one ranged GET per concept**.
At the 10,000-concept design target and the 300 s default that is 10,000 ranged GETs every five
minutes *per pod*. The backend's docstring and `docs/docs/advanced/knowledge-bases.md` must both say
so, and recommend a larger `refresh_seconds` — or `None` for an immutable bundle — for large S3
bundles.

**Envelope — corrected against measurement during iteration 8.** The design's "~50 MB for 10,000
concepts (~5 KB each)" does not survive contact with the implementation, in two independent ways:

- **The floor alone is 45 MB.** A 10,000-concept manifest whose concepts have *empty* bodies retains
  45 MB, dominated by ~190,000 pydantic objects (`pydantic/main.py:263`) — the `OKFConcept` instances
  and their field containers. Nothing about the token index is involved; that is the cost of holding
  10,000 parsed concepts at all.
- **The body token index was never actually bounded.** `BODY_INDEX_MAX_BYTES` bounds the bytes *read*,
  not the tokens *retained*, so `field_tokens["body"]` was an unbounded set over an 8 KiB window.
  Memory was therefore O(concepts x distinct body tokens), and the same 10,000-concept bundle with
  ordinary prose bodies measured **770 MB** — a real OOM risk in a 1 GB container, not a rounding error.

Iteration 8 adds `BODY_INDEX_MAX_TOKENS = 128`, applied to `body` only and collected in document order
so the kept subset is reproducible across processes. Measured on the same bundle:

| `BODY_INDEX_MAX_TOKENS` | 10,000-concept manifest |
|---|---|
| unbounded (as designed) | 770 MB |
| 256 | 253 MB |
| **128 (chosen)** | **182 MB** — ~19 KB per concept |
| 64 | 96 MB |
| no body index at all | 45 MB (the floor) |

`128` is chosen because `body` carries the lowest ranking weight (1, against `title` 4 and `tags` 3):
its job is recall on terms the frontmatter missed, so losing its tail costs far less than any other
field's would. The **declared envelope is therefore 250 MB, not 50 MB**, and the cost is stated per
concept — ~19 KB measured, 25 KB budgeted — because that is the figure that stays true at every bundle
size (measured constant to within 4 bytes at 1,000, 2,000 and 10,000 concepts).

A further ~80 MB is available without changing the ranking: `field_tokens` holds five `set`s per
concept, and a CPython set over-allocates its table to 5x its size, so the same tokens as sorted
tuples cost 85 MB where the sets cost 165 MB. That would need `OKFManager._score` to switch to
`bisect` membership and is **not** part of iteration 8 — recorded here so it is a decision someone
takes deliberately rather than a saving nobody knew was on the table.

Bodies themselves are still excluded from the manifest entirely; they are never retained between calls.

`max_concepts` truncation: the walk consumes `store.list()` in its contractual lexicographic order and
stops after `max_concepts` **accepted** concepts (skipped files do not consume budget), sets
`truncated=True`, and appends a `truncated` diagnostic naming the count and the limit. The bundle still
loads and serves.

#### Refresh and concurrency

```python
def _ensure_manifest(self) -> OKFBundle:
    manifest = self._manifest
    if manifest is None:                                   # initial load: blocking, nothing to serve
        with self._refresh_lock:
            if self._manifest is None:
                self._manifest = self._walk()
                self._loaded_at = time.monotonic()
            return self._manifest
    if self._refresh_seconds is None or (time.monotonic() - self._loaded_at) < self._refresh_seconds:
        return manifest
    if self._refresh_lock.acquire(blocking=False):          # refresh: never blocks a caller
        try:
            self._manifest = self._walk()
        except Exception as exc:
            log.warning("[%s] manifest refresh failed, serving the previous manifest: %s", self.backend_name, exc)
        finally:
            self._loaded_at = time.monotonic()
            self._refresh_lock.release()
    return self._manifest
```

The concurrency contract, in full:

- **`threading.Lock`, not an asyncio primitive.** The whole KB tier is synchronous, and the tools
  `KnowledgeBuilder.build()` returns are plain sync functions — a framework may run them on a thread
  pool, and the ECS/pipeline agent-runner topology runs several consumer threads per process.
- **Two concurrent callers crossing the boundary produce one walk.** The loser does not block and is
  served the current manifest, one interval stale.
- **The manifest is swapped as a whole** (a single attribute assignment), so no caller ever observes a
  half-built manifest.
- **A failed refresh keeps the previous manifest and resets the clock**, so an S3 outage costs one
  attempt per interval rather than one per tool call. The **initial** load propagates instead —
  `connect()` failing loudly is the right behavior for a misconfigured store.
- **`reload()`** forces an immediate walk under the blocking lock; `refresh_seconds=None` disables
  automatic refresh entirely.
- **A write racing a refresh**: `write()` inserts into the live manifest's `concepts` dict (atomic per
  key under CPython), while a refresh replaces the whole object. A write completing between a refresh's
  `_walk()` and its assignment is therefore dropped *from the manifest* — never from the store, where
  the bytes are already durable — and reappears on the next walk. Documented rather than locked
  against, because bundle-level write concurrency control is an explicit non-goal.

#### Operations

**`search(query, limit=3)`** — lexical, deterministic:

- Tokenisation: lowercase, split on `[^a-z0-9]+`, drop tokens shorter than two characters, applied
  identically to the query and to every indexed field.
- Field weights: `title` 4, `tags` 3, `type` 2, `description` 2, `body_tokens` 1. A concept's score is
  the sum, over distinct query tokens, of the weight of each field containing that token. Presence, not
  frequency — term frequency over a bounded body window would reward long preambles.
- Only concepts scoring `> 0` are returned. Ordering is `(-score, path)`, so ties break
  lexicographically and the result is reproducible across processes. Asserted by test.
- Records: `text` = `description` or `title` or `path`; `metadata` = `{id, source, title, kind: type,
  trust, stale}`. No `links` (the body is not complete).

**`fetch(ids)`** — ids in, records out, **in the order requested**. An unknown or unreadable id is
omitted with a logged warning (never an exception, never a placeholder record). Each record carries the
full body as `text` and the complete `links` list. A duplicate id yields one record.

**`browse(path="", limit=50)`**:

- If the browsed directory has an `index.md`, return **one** record whose `text` is that file's body,
  `metadata["kind"] = "index"`, `metadata["id"]` = the index path. `limit` does not truncate a curated
  listing. This holds at **any** level, not just the root — `index.md` is reserved everywhere.
- Otherwise derive the listing from the manifest: the immediate children of that directory, both
  concepts and subdirectories, in lexicographic order, truncated to `limit`. A subdirectory record has
  `metadata["kind"] = "directory"` and an `id` ending in `/`; a concept record is shaped like a
  `search` record.
- An unknown directory returns `[]` with a logged warning.

**`write(records)`**:

- Refuses when `capabilities.writable` is `False`, with `KnowledgeCapabilityError`.
- Path resolution per record:
  1. `metadata["id"]` when present — normalised through `normalise_relative`, and **rejected with
     `KnowledgePathError` if it contains a `,`** so every id the backend hands out round-trips through
     `fetch_kb`;
  2. otherwise **synthesised**: `f"{write_prefix}/{slug}-{uuid4().hex[:8]}.md"`, where `slug` is a
     comma-free `[a-z0-9-]` slug of `metadata["title"]`, else of `metadata["type"]`, else `"concept"`.
     Synthesis is required because `write_kb`'s signature carries no id and the design's non-changes
     freeze it. **[spec-level decision]** — [Deviations and additions](#deviations-and-additions) B.
- `type` is `metadata["type"]` when non-empty, else `"Note"` — a non-empty `type` is the whole
  conformance bar for a concept document, so it can never be omitted.
- Emitted document: `---\n` + `yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False,
  allow_unicode=True)` + `---\n\n` + `record["text"]`. Frontmatter key order is fixed as `type`,
  `title`, `description`, `tags`, `status`, `generated`, `sources`, then any caller extras, so two
  writes of the same content are byte-identical.
- `generated` is always stamped: `{"by": <producer>, "at": <ISO-8601 UTC, seconds precision>}`.
- **Write-through**: after `store.write_bytes` returns, the rendered document is parsed with
  `body_complete=True` and inserted into the live manifest, replacing any entry at that path. The
  concept is therefore visible to `fetch`, `browse`, and `search` in the very next call, independent of
  `refresh_seconds`.

**Producer string.** `producer` defaults to `f"agentkernel/{version}"`, where `version` comes from
`importlib.metadata.version("agentkernel")` — the idiom already used at
`deployment/aws/__init__.py:5-8` — falling back to `"agentkernel/unknown"` on
`PackageNotFoundError` (a fallback is required: the package is importable from a source tree without
distribution metadata). It is resolved **once in `__init__`**, not per write. An explicit `producer` is
used verbatim after a non-empty check; the `<producer>/<version>` shape is a spec *convention*, and the
same field legitimately carries `process:<id>` for automation, so the value is not pattern-validated.

**`_derived_schema()`** returns, read from the loaded manifest and never hand-transcribed:

```python
{"okf_version": bundle.okf_version, "concept_count": len(bundle.concepts),
 "types": sorted({c.type for c in bundle.concepts.values()}),
 "top_level_directories": sorted(...), "reserved_files": {"index": [...], "log": [...]},
 "diagnostics": len(bundle.diagnostics), "truncated": bundle.truncated}
```

**`get_description()`** returns `f"{backend_name}: {description}"` plus, when diagnostics exist,
`f" ({n} bundle diagnostic(s); first: {code} at {path})"` — surfaced, not swallowed. Diagnostics are
also logged at `warning` on each walk.

**`format_results`** overrides the base:
`- [<id>] <title> — <type> · trust=<tier>[ · STALE]`, falling back to the path when `title` is absent.
Prompt-visible by construction; asserted by test.

### `knowledgebase/knowledgebuilder.py` — the agent surface

The four existing tools keep their names and signatures. Three are added, each gated on the
**registered set**:

| Tool | Emitted when |
|---|---|
| `search_kb(backend, query, limit=3)` | some backend declares **both** `search` and `query` |
| `fetch_kb(backend, ids)` | some backend declares `fetch` |
| `browse_kb(backend, path="", limit=50)` | some backend declares `browse` |

- Appended in the order `search_kb`, `fetch_kb`, `browse_kb` after the existing four, so the tool list
  is stable across runs for a given registered set. A vector-only application's list is unchanged
  (`build()` returns the same four callables).
- Routing at a backend that does not declare the capability returns an actionable **string**, never an
  exception into the framework — matching `read_kb`'s existing behavior
  (`knowledgebuilder.py:118-119,128-130`): `f"Backend '{name}' does not support {capability}. Backends
  that do: {supported}."`
- `search_kb`'s narrower gate: for a search-only backend `read_kb` already reaches `search()`, so a
  second tool doing the same thing would only give the agent a redundant choice. Once emitted, it
  routes at **any** backend declaring `search`.
- `fetch_kb` splits `ids` on `,`, strips each segment, and drops empty segments. An all-empty argument
  returns the "provide at least one id" string.
- **Semantic-map resolution** (`knowledgebuilder.py:76-89`) is applied to `search_kb` queries,
  `fetch_kb` ids (per segment, after splitting), and `browse_kb` paths, so a bundle root can be an
  environment-swappable token.
- `get_schemas` gains the per-backend `try/except` its sibling `get_all_kb_descriptions` already has
  (`knowledgebuilder.py:185-187`), emitting `{"error": str(exc)}` for the failing backend instead of
  failing the whole call.
- `write_kb` stops setting `cypher_query`/`cypher_params`; it sets the generic `query`/`params` only.
  The `if resolved_query:` guard and every existing validation string are unchanged.
- **Defensive capability read**: `getattr(backend, "capabilities", None)` — a subclass that overrides
  `__init__` without calling `super().__init__()` has no `capabilities`, and `build()` must warn naming
  that backend and treat it as declaring nothing rather than raising `AttributeError` while building
  the tool list.
- **Exception scope is unchanged**: the tool bodies keep catching bare `Exception` and returning a
  string. Narrowing them would change which failures reach the agent as text; that is not this change.

### Consumer changes

#### `ChromaManager` (`chroma.py`)

- `__init__` calls `super().__init__(capabilities=KnowledgeCapabilities(kinds=["vector"], search=True,
  search_mode="semantic", writable=True), name=name)`.
- `read` → **`search`**, body and signature otherwise unchanged (`limit: int = 3` already matches the
  base).
- Unchanged: `connect`, `write`, `backend_name`, `get_description`, the `chromadb` extra.

#### `Neo4jManager` (`neo4j.py`)

- Capabilities: `kinds=["graph", "structured"], query=True, query_language="cypher", writable=True`.
- `read` → **`query`**, first parameter renamed `query` → `statement` to match the base, and the default
  `limit` moves from 10 to 3.
- `write` reads `metadata["query"]` first and falls back to `metadata["cypher_query"]` (same for
  `params`/`cypher_params`), and **skips a record carrying neither** with a logged warning instead of
  calling `_run(None, {})`:

```python
statement = meta.get("query") or meta.get("cypher_query")
params = meta.get("params") or meta.get("cypher_params") or {}
if not statement:
    log.warning("[neo4j.write] record carries no query; skipping. metadata keys=%s", sorted(meta))
    continue
self._run(statement, params)
```

#### `StarburstManager` (`starburst.py`)

- Capabilities: `kinds=["structured"], query=True, query_language="sql", writable=False`.
- **`self.schema` → `self.db_schema`** (`starburst.py:67`), with its three readers updated:
  `starburst.py:111` (`schema=self.db_schema or None` — the *trino* kwarg name is untouched),
  `starburst.py:116` (log line), `starburst.py:204` (the `source` string). The `schema=` **constructor
  keyword is unchanged**, so both call sites that pass it
  (`examples/cli/knowledgebase/openai/starburst/demo.py:22`, `.../multi/demo.py:99`) are untouched, and
  `manager.schema` now resolves to the inherited `schema()` method.
- `read` → **`query`**, first parameter renamed `query` → `statement`, and the default `limit` moves
  from **5** to 3. The design's behavioural-change list records only Neo4j's 10 → 3; Starburst's 5 → 3
  is the second instance — see [Deviations and additions](#deviations-and-additions) D.
- `write` raises `KnowledgeCapabilityError(self.backend_name, "write")` instead of
  `NotImplementedError` (`starburst.py:141`).
- The `[]`-on-failure behavior of `_execute` (`starburst.py:223,227`) is **left as is**. It is a real
  wart the design's motivation names, but changing it would alter what every existing Starburst
  deployment's agent sees on a query error, and the design does not ask for it. Noted so it is not
  mistaken for an omission.

#### `knowledgebase/__init__.py`

Rewritten from a single comment line to the PEP 562 lazy pattern of
`deployment/aws/__init__.py:13-66` — a `_LAZY_EXPORTS` name → submodule map, `__all__`,
`__getattr__`/`__dir__`, and a `TYPE_CHECKING`-only mirror block so mypy and IDEs still resolve the
real types:

| Name | Module |
|---|---|
| `KnowledgeBase`, `Record` | `.base` |
| `KnowledgeBuilder` | `.knowledgebuilder` |
| `KnowledgeCapabilities`, `KnowledgeMetadata`, `KnowledgeRecord` | `.model` |
| `KnowledgeError`, `KnowledgeCapabilityError`, `KnowledgePathError` | `.errors` |
| `DocumentKnowledgeBase` | `.document` |
| `DocumentStore`, `LocalDocumentStore`, `S3DocumentStore` | `.store` |
| `OKFManager` | `.okf.manager` |
| `OKFBundle`, `OKFConcept`, `OKFDiagnostic`, `TrustTier` | `.okf.model` |

This fixes the import documented at `docs/docs/core-concepts/overview.md:353` without making
`chromadb`/`neo4j`/`trino`/`boto3` eager. `ChromaManager`, `Neo4jManager`, and `StarburstManager` are
**deliberately not exported** — each pulls an optional SDK at module import, and the existing examples
import them from their concrete modules. The contract suites are not exported (they import `pytest`,
and as built they live under `ak-py/tests/` rather than in the package).

Asserted by test: every name in `__all__` resolves; importing `agentkernel.knowledgebase` and touching
`KnowledgeBase`/`OKFManager` leaves `chromadb`, `neo4j`, `trino`, and `boto3` out of `sys.modules`.

#### Example — `examples/cli/knowledgebase/openai/okf/`

New, in the shape of its siblings (`build.sh`, `demo.py`, `demo_test.py`, `__init__.py`,
`pyproject.toml`, `README.md`) plus a small checked-in bundle:

```
okf/
├── bundle/                     # ~6 concepts, exercising every tolerance rule
│   ├── index.md                # bundle root: okf_version: "0.2" + a curated listing
│   ├── log.md
│   ├── tables/
│   │   ├── index.md            # a non-root curated listing, honoured by browse()
│   │   ├── orders.md           # human-reviewed, links to customers.md
│   │   └── customers.md        # machine-confirmed
│   ├── datasets/orders_db.md   # unverified, unknown `type`
│   └── malformed.md            # no frontmatter -> skipped with a diagnostic
├── demo.py                     # LocalDocumentStore("./bundle") -> OKFManager -> KnowledgeBuilder
└── demo_test.py                # browse_kb -> fetch_kb -> read_kb against real bundle paths
```

`demo.py` needs **no** `add_schema()` call — that is the point of `derives_schema=True`, and the
example demonstrates it. It does register a `semantic_map` for the bundle root so the environment-swap
story is visible. `pyproject.toml` needs no KB extra (pyyaml is core); it depends on `agentkernel[openai,cli,test]`
like its siblings.

#### Documentation

| Surface | Change |
|---|---|
| `docs/docs/advanced/knowledge-bases.md:15-45` (`### KnowledgeBase`) | the five-operation set replaces the `read`/`write` pair; `KnowledgeCapabilities` and which tool each capability emits; `OKFManager` added to the backend list |
| same file, `## KnowledgeBuilder and Tools:47` | the three new tools and their gating |
| same file, new section | the OKF backend, `DocumentStore` local-vs-S3, `from_uri`, `refresh_seconds`/`max_concepts` and the refresh cost |
| same file, `### Minimal implementation:203-235` | **breaking**: the example subclass declares `capabilities` and calls `super().__init__(capabilities=...)`. As written today it defines no `__init__` at all, so it stops constructing outright — see [Deviations and additions](#deviations-and-additions) E |
| same file, `### Optional overrides:253-260` | add `_derived_schema()`; note `schema()` now always carries `capabilities` |
| `docs/docs/core-concepts/overview.md:353` | the documented import starts working; the surrounding bullet list gains the operation set |
| both pages | the two prompt-visible migrations: `schema()` gaining `"capabilities"`, and `StarburstManager.schema` → `db_schema` |

#### Dev skills

`.agents/skills/ak-dev-new-knowledgebase-integration/SKILL.md` is the one skill whose content the change
invalidates outright: its step 2 sketch calls `super().__init__()` with no arguments, its step 3
"Record Contract" predates `KnowledgeMetadata`, its step 4 tells authors to raise `NotImplementedError`
for a read-only backend, and it has no capability-declaration or `DocumentStore` step.
`.agents/skills/ak-dev-architecture/SKILL.md`'s Knowledge Bases section (the `KnowledgeBase` member
list and the four-tool `KnowledgeBuilder` line) and `ak-py/src/agentkernel/skills/ak-add-capabilities/`
also reference the old surface. Ordering these updates is `plan.md`'s final iteration.

### Security

Three obligations, each landing in exactly one place so no caller can forget it:

- **Containment belongs to the `DocumentStore`**, implemented once as `normalise_relative` and applied
  by every entrypoint plus the walk's own emitted paths. `DocumentKnowledgeBase` turns a refusal into
  an error result for the agent, but is never the only place an escape is detected. `..` segments,
  absolute paths, and symlinks resolving outside `LocalDocumentStore.root` are refused on access and
  skipped during traversal.
- **No network fetch of OKF reference fields.** `resource`, `sources[].resource`, and `computation`
  values that are absolute URLs are returned to the agent as data and never dereferenced by any part of
  the KB layer — the multimodal hook's stance on remote references
  (`core/multimodal/hooks.py:41,344`). Asserted by a test that fails if the parser or manager pulls in
  `urllib`/`httpx`.
- **Concept body text is untrusted content** authored by whoever produced the bundle. It is returned as
  data and nothing in the layer acts on instructions found inside it: no body text is ever passed to a
  store path, an `eval`, a subprocess, or a network call, and `type` values — which producers invent
  freely — are used only as opaque strings for ranking and schema derivation, never dispatched on.
  Executing `type: Attested Computation` concepts stays a non-goal; they are read like any other
  concept.

### Config changes

**None.** No `AKConfig` section is added (design decision 1), no field is renamed, and no `AK_*`
environment variable gains or loses meaning. YAML files and env vars written before this change behave
identically after it. Backends stay application-constructed; `DocumentStore.from_uri` keeps
local-in-dev / S3-in-prod a one-string change that the *application* reads from its own environment.

### Data compatibility

- **Chroma**: records written by the old `write_kb` carry `cypher_query`/`cypher_params` in their stored
  metadata. They are **not migrated** (design item 5, and an explicit non-goal). They read back exactly
  as before — the dead keys are inert data, and `format_results` never renders them.
- **Neo4j**: old-shape records (hand-written or already queued) keep working because `write` falls back
  to the `cypher_*` spelling.
- **OKF**: documents this change writes are ordinary v0.2 concept documents, readable by any conformant
  consumer, including the reference visualizer. Nothing is written outside `write_prefix` unless the
  caller supplies `metadata["id"]`.
- No on-disk or in-store format owned by AK changes.

### Behavioural changes

Items 1-13 are `design.md`'s list, restated only where this spec fixes a detail; 14-16 are new and are
flagged for design review. Each needs a test.

1. `KnowledgeBase.read` becomes concrete, routing on `capabilities.query`. `ChromaManager.read` →
   `search`; `Neo4jManager.read` and `StarburstManager.read` → `query`. A third-party subclass
   overriding `read()` keeps winning.
2. `StarburstManager.write` raises `KnowledgeCapabilityError`, not `NotImplementedError`. The new type
   does not subclass the old one; in-tree no caller catches it.
3. `schema()` no longer raises when `add_schema()` was skipped **and** `_derived_schema()` is non-empty.
   All three existing backends declare `derives_schema=False` and return `{}`, so their behavior is
   unchanged.
4. `schema()` output gains `"capabilities"` — additive, and prompt-visible through `get_schemas`.
5. `write_kb` no longer writes `cypher_query`/`cypher_params`. Agent-issued Neo4j writes are unaffected
   (item 12); already-stored Chroma metadata is not migrated.
6. `get_schemas` degrades per backend instead of failing the whole call.
7. `build()` returns up to seven callables rather than four.
8. `agentkernel.knowledgebase` exports names for the first time; the documented import starts working.
9. `StarburstManager`'s Trino schema name moves to `self.db_schema`. The `schema=` keyword is unchanged.
   `get_schemas` starts returning a real schema for Starburst instead of raising `TypeError` — a
   prompt-visible change for **every** Starburst deployment.
10. `format_results` prefixes `[<id>]` for backends declaring `fetch`. No existing backend does, so
    in-tree output is byte-identical.
11. `Neo4jManager.query` defaults to `limit=3` instead of `limit=10`. `read_kb` always passes `limit`,
    so only direct callers see it.
12. `Neo4jManager.write` reads the generic keys with the `cypher_*` fallback and skips a record carrying
    neither, with a warning.
13. `KnowledgeBase.__init__` requires `capabilities` (`name` optional) — the only signature in this
    change that is not backward compatible. **Its reach is wider than the design states**: it breaks
    not only a subclass that calls `super().__init__()` with no arguments, but also one that defines no
    `__init__` at all (it inherits the new required parameter, so `MyBackend()` raises `TypeError`).
    The documented example at `docs/docs/advanced/knowledge-bases.md:212` is exactly that shape.
14. **`StarburstManager.query` defaults to `limit=3` instead of `limit=5`** (`starburst.py:151`), the
    same class of change as item 11 and not listed in the design.
15. **`query()`'s first parameter is named `statement`, not `query`** — the base signature the design
    fixes. A caller using `neo4j.read(query="…")` or `starburst.read(query="…")` **by keyword** keeps
    working through the inherited `read()`, but a caller switching to `query(query="…")` gets a
    `TypeError`. In-tree there are no keyword callers of either.
16. **`read` and `write` are no longer abstract.** Additive for existing subclasses; a new subclass may
    now omit both, and the required abstract surface shrinks to `backend_name`, `connect`,
    `get_description`.

**Non-changes, to be asserted:**

- `Record` stays `Mapping[str, Any]` and stays the annotation on every signature; `KnowledgeMetadata`
  and `KnowledgeRecord` appear in no signature.
- `read`/`write` signatures, including `**kwargs`, which every new operation also carries; `read()`
  forwards `**kwargs` unchanged to the primitive it delegates to.
- The four existing tool names and signatures, and every existing tool error/validation string.
- `KnowledgeBuilder.__init__`'s `(backends, semantic_map)` signature and its duplicate/empty
  `backend_name` `ValueError`s.
- `add_schema` / `close`, and `format_results`' output for every backend declaring `fetch=False`.
- The `schema=` keyword on `StarburstManager.__init__`; the `ValueError` text in `schema()`.
- No `AKConfig` section, no framework-adapter change, no new optional extra.
- Every existing example under `examples/cli/knowledgebase/openai/` runs unmodified.

## Error handling

| Condition | Behavior |
|---|---|
| Undeclared operation called on a backend | `KnowledgeCapabilityError`, caught at the tool boundary and returned as an actionable string naming the backends that do declare it |
| Path escaping a store's namespace (agent path, concept link, or walk entry) | `KnowledgePathError` from the store; the walk skips the entry with a `path_escape` diagnostic; `fetch`/`browse` drop that path with a logged warning; `write` refuses the record |
| Missing or unreadable document | `read_bytes` → `FileNotFoundError` → empty result plus a logged warning. Never a traversal, never a raise into the framework |
| Malformed concept | skipped with a diagnostic; the bundle still loads (conformance requirement) |
| Missing store configuration (unreadable root) | `ValueError` at construction, matching `starburst.py:102` |
| Missing `boto3` for `s3://` | `ImportError` naming the `aws` extra, via `require_extra` |
| Unresolvable `from_uri` value | `AKConfigError` |
| Manifest refresh failure | logged at `warning`; the previous manifest continues to serve; the clock resets so one attempt is made per interval |
| Initial manifest load failure | propagates out of `connect()` |
| Backend declaring `query=True` with no `query_language` (or the reverse), or declaring nothing at all | `ValueError` at construction, naming the backend |
| `write` on a non-writable backend or store | `KnowledgeCapabilityError` before any I/O |

Exception scope, stated because the design does not: the only broad `except Exception` handlers are the
pre-existing ones in the tool bodies (which must return strings) and the manifest-refresh guard (which
must not let a transient store failure kill a serving pod). Everywhere else the caught types are
enumerated: `FileNotFoundError`, `yaml.YAMLError`, `ClientError`, `KnowledgePathError`.

## Testing

Run with `cd ak-py && uv run pytest`. CI installs `uv sync --all-extras` (`ak-py/build.sh:9`), so
`chromadb`, `neo4j`, `trino`, and `boto3` are importable in the test environment — their *clients* are
still mocked; no test touches a live service.

**No existing test file changes.** There are no tests referencing the knowledge-base tier today
(verified by grep over `ak-py/tests/`), so this change moves **no** patch targets — it only adds files.

| New file | Asserts |
|---|---|
| `tests/test_knowledgebase_model.py` | `KnowledgeCapabilities` defaults and `model_dump()` shape; `validate_capabilities` — reachability, both directions of query coherence, the reachability check reported first, each message naming the given subject; the class-name fallback when `name` is omitted; that constructing a `KnowledgeCapabilities` alone never validates |
| `tests/test_knowledgebase_base.py` | `read()` routes to `query()` when `capabilities.query` and to `search()` otherwise, forwarding `**kwargs` and `limit`; a subclass overriding `read()` still wins; undeclared operations raise `KnowledgeCapabilityError` naming backend and operation; `schema()` precedence (`backend` overridable, `capabilities` not, derived beaten by `add_schema`), the relaxed guard, and the byte-identical `ValueError`; `format_results` gating (fetch off, fetch on with/without a usable `id`) |
| `tests/test_knowledgebase_builder.py` | **the riskiest consumer.** Tool-list gating for every combination (vector-only → exactly the four; fetch-only; browse-only; search+query → `search_kb`); tool order; capability-mismatch strings; `write_kb` emitting `query`/`params` and **not** `cypher_*`; `get_schemas` degrading per backend; semantic-map resolution on `search_kb` queries, `fetch_kb` ids (per segment) and `browse_kb` paths; `fetch_kb` id splitting/stripping/empty-dropping; a backend missing `capabilities` warning instead of raising |
| `tests/test_knowledgebase_stores.py` | `DocumentStoreContract` over `LocalDocumentStore` (real `tmp_path`) and `S3DocumentStore` (fake boto3 client, including a paginated `list_objects_v2` and `NoSuchKey` → `FileNotFoundError`); containment matrix (`..`, absolute, backslash, normalising escapes) on every entrypoint; a symlink out of `root` skipped by `list()` and refused on read; global lexicographic ordering including the `a/z.md` vs `ab/b.md` case; `writable` probing vs declaration; `write_bytes` refused on a read-only store; `read_prefix_bytes` default vs the S3 ranged GET; `from_uri`'s five branches including `python:` and an `AKConfigError` scheme |
| `tests/test_knowledgebase_okf_parser.py` | frontmatter splitting (missing open/close, non-mapping YAML); `type` required, unknown `type` kept; unknown keys → `extra`; bare `verified` → one-element list; scalar `tags`; the three trust tiers; staleness against an injected `now`, and the unparseable case; link extraction in both forms plus relative resolution, escapes dropped, absolute URLs ignored, non-`.md` ignored; **v0.2-only**: a v0.1 `timestamp` lands in `extra` and a body `# Citations` list stays body text; every diagnostic code is reachable; no `urllib`/`httpx` import on any path |
| `tests/test_knowledgebase_okf_manager.py` | capabilities built from the store (writable folding both ways); `_derived_schema()` keys against a known bundle; `schema()` working with no `add_schema()`; search ranking — weights, presence-not-frequency, `(-score, path)` determinism across two managers, zero-score exclusion; `fetch` order/dedup/unknown-id omission and links present only here; `browse` index-vs-derived at root **and** at `tables/`, `limit` truncation, unknown directory; `write` — synthesised vs supplied id, comma refusal at both ends, fixed key order and byte-identical re-render, `generated` stamp, producer default and override; **write-through visibility with `refresh_seconds=None`** (proving it is not a refresh); refresh timing with a monkeypatched `time.monotonic`; a failed refresh serving the stale manifest and resetting the clock; `reload()`; **one walk under two concurrent boundary-crossing callers** (a `threading.Barrier` plus a walk counter); `max_concepts` truncation keeping a lexicographic prefix with a `truncated` diagnostic; nothing filtered on trust or staleness; diagnostics surfaced through `get_description()` |
| `tests/test_knowledgebase_okf_envelope.py` | the declared scale. A session-scoped fixture generates a 10,000-concept bundle in `tmp_path`; the test asserts the walk keeps all 10,000, that every concept's body index sits at the cap, that ranking is deterministic, and that `max_concepts` truncates to a lexicographic prefix with a diagnostic. Memory is measured as the sum of `size_diff` over a `snapshot_after.compare_to(snapshot_before, "filename")` around `_walk()` — **not** process RSS, which moves with the interpreter and the allocator's retained arenas — and asserted **per concept** against a 25 KB budget (250 MB projected at 10,000), because the cost is linear in the concept count and the per-concept figure is what stays true at every size. The measurement runs over a 2,000-concept slice: `tracemalloc` around a full 10,000-concept walk costs 75 s under coverage to learn the same number |
| `tests/test_knowledgebase_contract.py` | `KnowledgeBaseContract` run against `FakeKnowledgeBase` (four capability shapes), `OKFManager` over a real local bundle, and the three existing backends with mocked clients — `monkeypatch` on `chromadb.PersistentClient`, `neo4j.GraphDatabase.driver`, and `trino.dbapi.connect` (plus host/user/password constructor args for Starburst) |
| `tests/test_knowledgebase_exports.py` | every `__all__` name resolves; `chromadb`/`neo4j`/`trino`/`boto3` stay out of `sys.modules` after importing the package and touching `KnowledgeBase`/`OKFManager`; no contract suite is exported; the `overview.md:353` import works verbatim |
| `examples/cli/knowledgebase/openai/okf/demo_test.py` | the example-level convention (`Test("demo.py")`, ordered cases): the agent browses the bundle, fetches a concept by its real path, and answers from it |

> **As built:** the contract suites shipped as `ak-py/tests/knowledgebase_contracts.py`, not as a
> `knowledgebase/testing.py` inside the package. They are a suite this repo holds its own backends
> to, not a published helper for out-of-tree authors, so there is no
> `agentkernel.knowledgebase.testing` module to import.

Two reusable suites ship in the `SandboxProviderContract` (`sandbox/testing.py:130`) /
`QueueTransportContract` shape — subclass, override one fixture, and pytest collects the contract
against your backend. Neither class name is prefixed `Test`, and the module holding them is not
named `test_*`, so pytest collects neither on its own.

`KnowledgeBaseContract` asserts, for any backend: declared capabilities match implemented operations
(each declared one returns a list; each undeclared one raises `KnowledgeCapabilityError`); `schema()`
is callable and returns a `Mapping` — the regression guard for the `StarburstManager` attribute/method
collision; records carry a non-empty string `metadata["id"]` **containing no `,`** when `fetch` is
declared, generalised as "a backend whose ids cannot be comma-free must not declare `fetch`"; unknown
keys round-trip at **both** the record and the metadata level; every operation accepts `**kwargs`;
both construction-time invariants are enforced and each error names the backend without reading
`backend_name`; `read()` routes on `capabilities.query`; and `derives_schema=True` implies a non-empty
`_derived_schema()`.

`DocumentStoreContract` asserts: round-trip `write_bytes`/`read_bytes`/`exists`; `FileNotFoundError` on
a missing path; `list()` global lexicographic order and prefix filtering; containment refusal on every
entrypoint; `read_prefix_bytes` returning a prefix of `read_bytes`; and `write_bytes` raising when
`writable` is `False`.

## Deviations and additions

Nothing below changes the design's shape; each is a detail the design left open or a claim it scoped
too narrowly. Flagged for design re-review per the staged process rather than absorbed silently.

| | Item | Why |
|---|---|---|
| A | **`KnowledgePathError`**, a third error type in `errors.py` | The design has the store refuse an escaping path and `DocumentKnowledgeBase` map the refusal to an agent-facing result. That mapping needs a type to catch; `ValueError` would also swallow unrelated failures |
| B | **`write_prefix` and id synthesis** on `OKFManager.write` | `write_kb`'s signature carries no id and the design freezes it as a non-change, so an agent-issued OKF write has no way to name a bundle path. Without synthesis the design's write path is unreachable from the agent surface |
| C | **`DocumentStore.read_prefix_bytes`**, a sixth method with a default implementation | Makes the eager frontmatter pass affordable over S3 (a bounded ranged GET per concept instead of a full object). Defaulted, so a bring-your-own store need not implement it |
| D | **Two behavioural changes the design's list omits** (items 14-15): `StarburstManager`'s default `limit` 5 → 3, and `query()`'s first parameter named `statement` | The design's item 11 quantifies over Neo4j only; `starburst.py:151` is a second instance, and the parameter rename is implied by the base signature the design fixes |
| E | **Migration item 13's reach** | The design scopes it to "a subclass calling `super().__init__()` with no arguments". A subclass defining no `__init__` at all also breaks — which is exactly the shape of the documented example at `docs/docs/advanced/knowledge-bases.md:212` |
| F | **The manifest retains a bounded body token index, not bodies** | "Frontmatter parsed eagerly, bodies read lazily" and "search ranks over body text" cannot both hold literally. A bounded token set per concept satisfies both intents; full bodies (and therefore complete `links`) are read only by `fetch`, which is how the design already describes traversal. **Amended in iteration 8:** the index as first implemented was bounded in *bytes read* but not in *tokens retained*, which is not the same promise — see [Manifest envelope](#manifest-what-is-retained-and-what-it-costs) for the measurements, the `BODY_INDEX_MAX_TOKENS` cap that closes it, and the corrected 250 MB envelope |
| G | **`capabilities` is not overridable via `add_schema()`**, and `search_mode` is deliberately not bidirectional with `search` | Two precedence/scope questions the design leaves open; both resolved in the direction that keeps the declaration honest |

## Next stage

`plan.md` (stage 3) orders this into iterations and is not written until this document is reviewed.
