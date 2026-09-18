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

**Amended 2026-09-18 — [A2]**, tracing `design.md`'s amendment of the same date. Three things change
here: `KnowledgeBase.read()` is **removed** and its routing moves into `read_kb`; `search_kb`'s gate
relaxes to any `search`-declaring backend; and OKF gains a **configuration-driven role layer** — an
`okf` block naming `consumer` / `producer` / `curator` agents per database, with Agent Kernel
constructing the backends and binding the tools and prompt. The blast radius grows by exactly two
files outside `knowledgebase/`: `core/config.py` (the new block) and `core/tool.py` (one factory
branch). Amended and new sections are marked **[A2]**; superseded text is kept under
**Superseded by [A2]**.

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
├── base.py               # CHANGED: capability-aware ABC, schema derivation ([A2] read() removed)
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
    ├── manager.py        # NEW: OKFManager
    ├── roles.py          # [A2] NEW: OKFRole, OKFAssignment, OKFRoleRegistry
    ├── capability.py     # [A2] NEW: OKFCapabilityManager (config -> stores/managers/builders)
    ├── prompts.py        # [A2] NEW: OKFPromptComposer + the per-role mandate text
    └── tools.py          # [A2] NEW: OKFToolFactory + the agent-facing tool callables
```

Rules governing the package, each stated so a reviewer can check it mechanically:

1. **`okf/` never touches a `DocumentStore` or the network.** `parser.py` takes `bytes`/`str` and a
   path string, and returns objects. Asserted by a test that imports `agentkernel.knowledgebase.okf`
   and fails if `agentkernel.knowledgebase.store` appears in `sys.modules` on its account.
2. **`store/` never knows markdown, YAML, or OKF.** No import of `yaml` or of `okf/` anywhere under
   `store/`.
3. **Stores take explicit constructor parameters and never read `AKConfig`** — the shared-driver and
   transport rule. `from_uri` is a string parser, not a config reader.
4. **[A2] Config reading lives in `okf/capability.py` only.** `OKFCapabilityManager` is the single
   reader of the `okf` block; `OKFManager`, `DocumentStore`, and `KnowledgeBuilder` keep taking
   explicit constructor parameters and never call `AKConfig.get()` — rule 3 extended to the new layer.
   `roles.py` is given a parsed config object, never the singleton.
5. **[A2] The role vocabulary does not leave `okf/`.** `consumer`/`producer`/`curator` appear in
   `okf/roles.py`, `okf/prompts.py`, `okf/tools.py`, and the `_OKFConfig` field names — nowhere else.
   `knowledgebuilder.py` gains no agent, role, or OKF awareness, and `SystemToolFactory` sees only an
   opaque `list[SystemTool]`.
6. **The contract suites import `pytest`** and therefore live in `knowledgebase/testing.py`,
   outside the package's lazy export map — importable by name from test code, exactly as
   `sandbox/testing.py` and `pipeline/testing.py` are, so `import agentkernel.knowledgebase`
   never pulls pytest.

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
        # backend_name is deliberately not read here: subclasses assign what it reads only
        # after super().__init__(). The operations below may read it, because by then the
        # subclass is fully constructed.
        self.validate_capabilities(capabilities, name or type(self).__name__)

    @staticmethod
    def validate_capabilities(capabilities: KnowledgeCapabilities, subject: str) -> None: ...

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

```

- **[A2]** There is **no `read()` on the ABC.** The class ends at `write()`. The routing rule it used
  to carry now lives in `read_kb` (see [the agent surface](#knowledgebaseknowledgebuilderpy--the-agent-surface));
  the rule itself is byte-for-byte the same, only its home moves.
  - The removal is what makes the operation set honest: every member of the ABC is now a capability a
    backend declares, and nothing on it is a convenience router over the others.
  - A third-party subclass that overrode `read()` keeps the method — Python does not care — but
    nothing calls it. To stay reachable it must declare and implement `search` or `query`.
    Behavioural change 18.
- `read` and `write` **stop being abstract** (`read` by being deleted outright). A subclass that
  implements `write` keeps working unchanged; a new subclass may omit it. `connect`, `backend_name`,
  and `get_description` stay abstract, so the required surface shrinks from five members to three.
- The default operations raise with `self.backend_name`, which is safe: by the time an operation is
  called the subclass is fully constructed. Only the **construction-time** validation is forbidden from
  reading the property.
- **Corrected 2026-09-18.** This section first specified `validate_capabilities` as a **module-level
  function**. It is implemented as a **`@staticmethod` on `KnowledgeBase`** (`base.py:51-52`), which
  is the correct form and what the rest of this spec should be read against.
  - The stated intent is unchanged and still met: being static is exactly what lets
    `KnowledgeBaseContract` exercise it **without constructing a backend** —
    `KnowledgeBase.validate_capabilities(KnowledgeCapabilities(), "probe-backend")`
    (`knowledgebase/testing.py:481-506`), and the same call shape in
    `tests/test_knowledgebase_model.py:142-178`.
  - A static method is also what the house rules require: *"a helper that only makes sense next to one
    class is a method (`@staticmethod`/`@classmethod` when it needs no instance) of that class"*
    (`ak-dev-code-quality`, Classes not script-style functions). A module-level function here would
    belong to no other caller and would have been the departure.
  - `__init__` calls it as `self.validate_capabilities(...)`, so a subclass may override the
    validation; no in-tree backend does.

```python
    @staticmethod
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

class DiagnosticCode(str, Enum):
    ...                # one member per row of the table below

class OKFDiagnostic(BaseModel):
    path: str          # "" for bundle-level diagnostics
    code: str          # a DiagnosticCode value, but an open str
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
    links: list[str] = Field(default_factory=list)   # populated only when body is complete
    field_tokens: dict[str, set[str]] = Field(default_factory=dict)  # ranker field -> tokens

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

`DiagnosticCode` is the single source of these strings for both the parser and the manager, which
would otherwise repeat them. It is deliberately **not** the annotation on `OKFDiagnostic.code`: a code
emitted by a future producer must still round-trip through the model, so the field stays an open `str`
and the enum gates nothing.

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

class OKFParserUtil:
    @staticmethod
    def decode_document(data: bytes) -> str: ...
    @staticmethod
    def tokenise(text: str) -> set[str]: ...
    @staticmethod
    def is_reserved(path: str) -> bool: ...
    @staticmethod
    def split_frontmatter(data: str) -> tuple[str | None, str]: ...
    @staticmethod
    def derive_trust(verified: list[dict[str, Any]]) -> TrustTier: ...
    @staticmethod
    def is_stale(stale_after: str | None, now: datetime) -> tuple[bool, list[OKFDiagnostic]]: ...
    @staticmethod
    def extract_links(concept_path: str, body: str) -> tuple[list[str], list[OKFDiagnostic]]: ...
    @staticmethod
    def parse_concept(path: str, data: str, *, body_complete: bool, now: datetime | None = None) -> tuple[OKFConcept | None, list[OKFDiagnostic]]: ...
    @staticmethod
    def parse_index(path: str, data: str, *, is_root: bool) -> tuple[str, str | None, list[OKFDiagnostic]]: ...
```

- **A class of static methods, not module-level functions.** Parsing an OKF document depends on
  nothing but the document — no connection, no cache, no configuration — so nothing is held on an
  instance; the class exists to give the reserved-file rules, the tolerance rules and the tokeniser one
  named owner, which is what the repo's classes-not-scripts rule asks for and what the manifest walk in
  `OKFManager` reaches for.
- `tokenise` lives here, next to the body index it fills, so the query side and the index side
  provably share one definition — that shared definition is what makes ranking reproducible across
  processes.
- `decode_document` decodes `utf-8-sig` with `errors="replace"` and never raises. Both halves are
  load-bearing: the walk reads a bounded *prefix*, which can cut a multi-byte character in half, and a
  leading byte-order marker under plain `utf-8` would make the opening `---` unrecognisable and drop the
  whole concept.
- `is_reserved` compares the basename case-insensitively, for the same reason: bundles travel as git
  repos and tarballs across case-insensitive filesystems, where treating `Index.md` as a concept would
  mint a concept colliding with its directory's index.
- `parse_concept` takes an injectable `now` so staleness is testable without freezing the clock
  globally; it defaults to the current UTC time.

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
- `field_tokens` is built once per concept and keyed by the ranker's field names (`type`, `title`,
  `description`, `tags`, `body`); the `body` entry is tokenised from the body bytes inside that window.
  `body` and `links` are left `None`/empty, and `body_complete=False` is recorded. Tokenising per field
  at parse time rather than per query is what keeps `search` a scan over sets rather than a re-tokenise
  of the whole bundle.
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

`reload()` and `write()` are the two calls that can *block* on a walk rather than merely trigger one.
`reload()` forces one and waits for it by definition. `write()` waits because it applies its
write-through under `_refresh_lock` (see the concurrency contract below): a write issued while a
refresh walk is in flight blocks for the remainder of that walk — on a large S3 bundle, up to the full
`list_objects_v2` pagination plus one ranged GET per concept — before its own concepts enter the
manifest. The store write itself is already durable by then; what waits is manifest visibility. This
is another reason a large S3 bundle wants a long `refresh_seconds`: it makes the window a write can
land in proportionally rarer.

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
- **A write racing a refresh is not dropped.** `write()` takes `_refresh_lock` *blocking* and applies
  its write-through to whatever manifest is current at that moment, not to the one the call started
  with. A refresh that replaced the manifest between the write's `_walk()`-time and its insert would
  otherwise discard the write-through and hide an already-durable concept until the next walk; holding
  the lock closes that window, so a written concept is visible to the very next operation under every
  interleaving. Pinned by `test_a_refresh_landing_mid_write_does_not_discard_the_write_through`.
  **[spec-level decision]** — [Deviations and additions](#deviations-and-additions) I. This is *manifest*
  concurrency only: bundle-level write concurrency control (two processes writing one path) remains an
  explicit non-goal, and the store is still last-writer-wins.

#### Operations

**`search(query, limit=3)`** — lexical, deterministic:

- Tokenisation: lowercase, split on `[^a-z0-9]+`, drop tokens shorter than two characters, applied
  identically to the query and to every indexed field.
- Field weights (`_FIELD_WEIGHTS`, keyed to match `OKFConcept.field_tokens`): `title` 4, `tags` 3,
  `type` 2, `description` 2, `body` 1. A concept's score is the sum, over distinct query tokens, of the
  weight of each field containing that token. Presence, not frequency — term frequency over a bounded
  body window would reward long preambles.
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
  `body_complete=False` — the same terms the walk parses on, because a manifest that retained complete
  bodies would grow without bound — and inserted into the live manifest, replacing any entry at that
  path. The concept is therefore visible to `fetch`, `browse`, and `search` in the very next call,
  independent of `refresh_seconds`. `metadata["links"]` appears only after a `fetch` of the written
  path, exactly as for a walked concept. The batch's inserts are applied **once, under
  `_refresh_lock`, to whatever manifest is current then** — never to the object the call started with,
  which a concurrent refresh may already have replaced. See the concurrency contract above for the
  guarantee and its cost.
- **Path handling is normalisation, not resolution.** Every id in the batch runs through
  `normalise_relative` before the first `write_bytes`, so a malformed or comma-bearing id fails the call
  while it is still a no-op. The store's own containment check (`realpath` against `root`) necessarily
  runs per write, so an id that escapes only through a symlink is refused part way through a batch, with
  the records before it already durable. Batch atomicity is not offered; the two checks are stated
  separately so that is not read as a promise.
- A document this class rendered that fails to parse back is logged at `warning` and skipped rather than
  raised: the bytes are durable either way, and the concept reappears on the next walk. It is unreachable
  in practice, but a silent `continue` would turn it into a durable write invisible until then.

**Producer string.** `producer` defaults to `f"agentkernel/{version}"`, where `version` comes from
`importlib.metadata.version("agentkernel")` — the idiom already used at
`deployment/aws/__init__.py:5-8` — falling back to `"agentkernel/unknown"` on
`PackageNotFoundError` (a fallback is required: the package is importable from a source tree without
distribution metadata). It is resolved **once in `__init__`**, not per write. An explicit `producer` is
used verbatim after a non-empty check; the `<producer>/<version>` shape is a spec *convention*, and the
same field legitimately carries `process:<id>` for automation, so the value is not pattern-validated.

**`_derived_schema()`** returns, read from the loaded manifest and never hand-transcribed. Its
`top_level_directories` comes from `_child_directories(manifest, "")` — the same derivation `browse`'s
listing uses, over concepts **and** reserved files, so a directory curated by nothing but an `index.md`
is named by the schema the agent reads first as well as reachable from the root listing. Deriving it
from concept paths alone would let the two views of the bundle disagree:

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
| `search_kb(backend, query, limit=3)` | **[A2]** some backend declares `search` (was: both `search` **and** `query`) |
| `fetch_kb(backend, ids)` | some backend declares `fetch` |
| `browse_kb(backend, path="", limit=50)` | some backend declares `browse` |

**[A2] `read_kb` owns the routing rule.** With `read()` gone from the ABC, the tool body branches
directly:

```python
def read_kb(backend: str, query: str, limit: int = 3) -> str:
    db = self.backends.get(backend)
    if not db:
        return f"Unknown backend '{backend}'. Available: {list(self.backends.keys())}"
    if not self._declares(db, "search") and not self._declares(db, "query"):
        return self._unsupported(backend, "reads", "search", "query")
    resolved = self._resolve_placeholders(query, backend)
    rows = db.query(resolved, limit=limit) if self._declares(db, "query") else db.search(resolved, limit=limit)
    return db.format_results(rows)
```

- The `**kwargs` forwarding the old `read()` performed has no caller at the tool layer — `read_kb`'s
  signature takes none — so it disappears with the method rather than being reproduced. A programmatic
  caller wanting backend options calls `search()`/`query()` directly, which still accept `**kwargs`.
- The neither-`search`-nor-`query` guard stays exactly where it is (`knowledgebuilder.py:199-202`):
  without it a backend declaring neither would report a missing `search` the agent never asked for.

- Appended in the order `search_kb`, `fetch_kb`, `browse_kb` after the existing four, so the tool list
  is stable across runs for a given registered set. A vector-only application's list is unchanged
  (`build()` returns the same four callables).
- Routing at a backend that does not declare the capability returns an actionable **string**, never an
  exception into the framework — matching `read_kb`'s existing behavior
  (`knowledgebuilder.py:118-119,128-130`): `f"Backend '{name}' does not support {capability}. Backends
  that do: {supported}."`
- **Superseded by [A2]** — `search_kb`'s narrower gate: for a search-only backend `read_kb` already
  reaches `search()`, so a second tool doing the same thing would only give the agent a redundant
  choice.
- **[A2]** The gate is now `self._backends_declaring("search")`, identical in shape to `fetch_kb`'s and
  `browse_kb`'s. OKF declares `search` with no query language, so under the old gate an OKF-only
  application received no `search_kb` at all.
  - The redundancy the old gate avoided is now real for every search-only backend, and is handled in
    the **docstrings** rather than denied. `search_kb`'s current text — *"Use this instead of read_kb
    when the backend also accepts a query language and you want relevance ranking rather than an exact
    statement"* (`knowledgebuilder.py:278-279`) — describes a distinction that no longer holds for
    those backends and is rewritten to: `read_kb` is the backend-agnostic entry point that routes on
    the backend's own declaration; `search_kb` always performs relevance retrieval and fails on a
    backend that cannot. Behavioural change 19.
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

#### [A2] `build(writable: bool = True)`

```python
def build(self, writable: bool = True) -> list[Callable]:
    tools = [get_schemas, read_kb, get_all_kb_descriptions]
    if writable:
        tools.insert(2, write_kb)      # keeps the historical order: schemas, read, write, descriptions
    ...
```

- The default is `True`, so every existing call returns the same callables in the same order. Only an
  explicit `build(writable=False)` omits `write_kb`.
- Position matters as much as presence: the original four are emitted in a fixed order the design
  freezes, so `write_kb` is inserted at index 2 rather than appended.
- **Why presence and not a per-call refusal**: `write_kb`'s per-call `writable` check stays exactly as
  it is for backends declaring `writable=False`. This parameter answers a different question — a
  *consumer agent* must not be told the tool exists, because an advertised tool it may never use is
  prompt surface spent on a dead end. Behavioural change 20.

#### [A2] Per-backend semantic maps

```python
def __init__(
    self,
    backends: list[KnowledgeBase],
    semantic_map: Optional[dict[str, str]] = None,
    backend_semantic_maps: Optional[dict[str, dict[str, str]]] = None,
) -> None:
```

- `semantic_map` keeps its exact meaning — one map applied to every registered backend — so every
  current caller is unaffected. `backend_semantic_maps` maps a **backend name** to its own map.
- `_resolve_placeholders` takes the backend name and resolves against that backend's map merged
  **over** the flat one, so a shared token can be overridden per backend without restating the rest.
- Required because `okf.databases.<name>.semantic_map` is declared per database and one agent's
  builder holds several. Flattening them would make two databases binding the same token to different
  paths unrepresentable — silently wrong rather than rejected.
- An entry naming a backend the builder does not hold is ignored with a warning, not an error: the OKF
  layer passes each builder only its own subset's maps, so a mismatch is a bug in that layer rather
  than bad user config. Behavioural change 21.

### [A2] `knowledgebase/okf/roles.py` — the role model

```python
class OKFRole(StrEnum):
    CONSUMER = "consumer"
    PRODUCER = "producer"
    CURATOR = "curator"

    @property
    def writable(self) -> bool:
        return self is not OKFRole.CONSUMER


@dataclass(frozen=True)
class OKFAssignment:
    database: str
    role: OKFRole


class OKFRoleRegistry:
    # Agent name -> the databases it holds a role in. Built once from the config block.

    def __init__(self, assignments: Mapping[str, tuple[OKFAssignment, ...]]) -> None: ...

    @classmethod
    def from_config(cls, databases: Mapping[str, "_OKFDatabaseConfig"]) -> "OKFRoleRegistry": ...

    def assignments_for(self, agent_name: str) -> tuple[OKFAssignment, ...]: ...
    def databases_for(self, agent_name: str) -> tuple[str, ...]: ...
    def writable_databases_for(self, agent_name: str) -> frozenset[str]: ...
    def may_write(self, agent_name: str, database: str) -> bool: ...
    def has_any_role(self, agent_name: str) -> bool: ...
```

- `OKFRole.writable` is the **single** place the producer/curator-vs-consumer distinction is encoded.
  Every permission question routes through it, so a fourth role later touches one property rather than
  a scattering of `in ("producer", "curator")` comparisons.
- `from_config` performs the two role validations the design requires, each raising `AKConfigError`
  (`core/util/factory.py`) naming the database:
  - a database whose three lists are all empty;
  - an agent named in both `producer` and `curator` of the **same** database. The check is
    per-database, so the same agent as `producer` of one and `curator` of another passes.
- Immutable after construction — assignments are tuples and the lookup maps are built once — so it is
  safe to read from the consumer threads an agent-runner fleet uses, with no lock.
- A plain class over a parsed mapping that **never** touches `AKConfig`, which is what lets tests build
  one from a literal dict.

### [A2] `knowledgebase/okf/capability.py` — `OKFCapabilityManager`

The process-wide owner of everything the config block describes — the `ConversationThreadManager` /
`ExecutionManager` singleton pattern, including `get()` returning `None` when the capability is off.

```python
class OKFCapabilityManager:
    _instance: ClassVar[Optional["OKFCapabilityManager"]] = None
    _lock: ClassVar[RLock] = RLock()

    @classmethod
    def get(cls) -> Optional["OKFCapabilityManager"]:
        # None when no `okf` block is configured - the enabled-check for the whole layer.

    @classmethod
    def reset(cls) -> None:
        # Test seam, matching ScheduleManager.reset().

    @property
    def roles(self) -> OKFRoleRegistry: ...

    def backend(self, database: str) -> OKFManager:
        # The manager for one database, constructed on first use and cached.

    def builder_for(self, agent_name: str) -> Optional[KnowledgeBuilder]:
        # That agent's KnowledgeBuilder over only its own databases; None when it holds no role.

    def validate_configuration(self) -> None:
        # Forces the role and store-resolution checks without walking any store.
```

- **Construction is lazy and per database.** `OKFManager.connect()` walks the whole store from
  `__init__` and blocks by design, so building every configured bundle eagerly would move N store
  walks into agent construction. `backend()` builds on first use under the lock and caches;
  `builder_for()` does the same per agent. This is what makes the design's "construction order does
  not matter" claim true in code.
- **One `OKFManager` per database, shared** across every agent's builder. Two agents reading the same
  bundle pay one walk and one refresh cycle, not two.
- `builder_for` passes `backend_semantic_maps` holding only that agent's databases, per the warning
  rule above.
- **Store resolution** reuses `DocumentStore.from_uri` for the built-ins and `resolve_dotted` for a
  dotted-path `type`, then asserts agreement:

  | `type` | Resolution | Agreement check |
  |---|---|---|
  | `local` | `DocumentStore.from_uri(uri)` | `uri` must not start with `s3://` |
  | `s3` | `DocumentStore.from_uri(uri)` | `uri` must start with `s3://` |
  | dotted path | `resolve_dotted(type, base=DocumentStore, error=AKConfigError)(uri)` | none — a custom store defines its own uri meaning |

  A disagreement raises `AKConfigError` naming the database, the declared `type` and the `uri`.
- **`validate_configuration()`** is called by the factory branch below before any tool is built, so a
  bad block fails at agent construction rather than inside the first tool call. It does **not** walk
  the stores; that stays lazy.
- **Writability warning** (`design.md` decision 19): when a database's resolved store reports
  `writable=False` while the block names a `producer` or `curator` for it,
  `validate_configuration()` logs a `WARNING` naming the database and every affected agent, and
  returns normally.
  - It deliberately does **not** raise, unlike the block's other validations. Those check the config
    text and are wrong wherever they run; this one checks the environment, and the same file is
    legitimately correct in production while the bundle is read-only in CI, under a read-only volume
    mount, or behind an S3 prefix whose write permission is invisible at construction time.
  - Message shape: `"OKF database '<name>' has a read-only store but names writable agents <agents>;
    their write_kb calls will be refused."` — it names the consequence, because the symptom
    (an agent that keeps trying to write and failing) is otherwise hard to trace back to config.
  - Reaching it requires resolving the store, which `_resolve_store` does without walking it.

### [A2] `knowledgebase/okf/prompts.py` — `OKFPromptComposer`

```python
class OKFPromptComposer:
    MANDATES: ClassVar[dict[OKFRole, str]] = {...}

    def __init__(self, registry: OKFRoleRegistry, descriptions: Mapping[str, str]) -> None: ...

    def compose(self, agent_name: str) -> str:
        # The whole OKF prompt section for one agent, or '' when it holds no role.
```

- Composed from **config alone** — database names, their `description` strings, and the role each
  assignment carries. No `OKFManager` is constructed to render it, which is the property that makes the
  prompt independent of construction order.
- Shape of the rendered section, in the sandbox's `[Capability]`-headed style:

```text
[Organizational knowledge (OKF)]
You have access to Open Knowledge Format bundles. Each is a navigable tree of concept documents,
not a search index - browse and fetch before you search.

Knowledge bases available to you:
- warehouse (read and write): Analytics warehouse concepts, one per table.
  Your role is PRODUCER: add new knowledge to this bundle as you learn it.
- policies (read only): Company policy knowledge.

How to use them:
1. Call get_schemas() once at the start of a session, never again.
...
```

- The navigation protocol the OKF example hand-writes today (`demo.py:45-72`) becomes the shared body
  of this text, so it ships with the capability. Its five steps are preserved in substance: schemas
  once, browse before search, fetch for the full concept and its links, search only when navigation
  fails, answer citing the concept path and its trust tier.
- The **per-role mandate** is one sentence per assignment, from `MANDATES`, rendered under the database
  it applies to. An agent holding different roles in different databases gets both mandates, each
  scoped to its own bundle — which is why the mandate is rendered per line rather than once per agent.
- The whole section rides the **first** `SystemTool.description`; the rest carry `""`, filtered out by
  `get_system_prompt_suffix`'s `if tool.description`. The sandbox pattern.

### [A2] `knowledgebase/okf/tools.py` — the agent surface

```python
class OKFToolFactory:
    @staticmethod
    def get_tools(agent_name: str | None) -> list[SystemTool]:
        # The OKF system tools for one agent; [] when it holds no role or the block is absent.
```

- **Which tools** is decided from config, without constructing a backend: every OKF backend declares
  `search`/`fetch`/`browse`/`derives_schema` unconditionally, so an agent with any role gets
  `get_schemas`, `get_all_kb_descriptions`, `read_kb`, `search_kb`, `fetch_kb`, `browse_kb`, plus
  `write_kb` when it holds a writable role in at least one database.
- **Each tool body is a closure over the agent name only**, resolving its builder on call:

```python
def read_kb(backend: str, query: str, limit: int = 3) -> str:
    builder = OKFToolFactory._builder(agent_name)      # -> manager.builder_for(agent_name)
    if builder is None:
        return "No OKF knowledge base is configured for this agent."
    return builder.read_kb(backend, query, limit)
```

  so agent construction neither builds a store nor walks a bundle, and a block edited between
  construction and first call is still honoured.
- **Read-side scoping is structural, not enforced.** The per-agent builder holds only that agent's
  databases, so `read_kb("policies", ...)` from an agent with no role in `policies` already returns
  `KnowledgeBuilder`'s own `"Unknown backend 'policies'. Available: [...]"`. No extra check is written,
  and `get_schemas` / `get_all_kb_descriptions` list only that agent's databases for the same reason.
- **Write-side scoping needs one wrapper**, because an agent may hold write on one of *its own*
  databases and not another:

```python
def write_kb(backend: str, text: str = "", source: str = "agent",
             query: str = "", params_json: str = "{}") -> str:
    manager = OKFCapabilityManager.get()
    caller = OKFToolFactory._calling_agent() or agent_name
    if manager and not manager.roles.may_write(caller, backend):
        writable = sorted(manager.roles.writable_databases_for(caller))
        return (f"Agent '{caller}' has read-only access to '{backend}'. "
                f"Knowledge bases it may write to: {writable}.")
    return builder.write_kb(backend, text, source, query, params_json)
```

- `_calling_agent()` reads `ToolContext.get().agent.name`, falling back to `Agent.current()`, then to
  the `agent_name` the closure was built with. The fallbacks matter: `ToolContext.get()` **raises**
  `RuntimeError` when no context is set (`core/tool.py:95-99`), and the closure's own name is correct
  in every case the context is missing, because the tool was attached to that agent.
- The refusal is a **string**, never an exception into the framework — the established tool-boundary
  behavior, and the same shape `_unsupported` already produces.
- `func.__name__` equals `SystemTool.name` for all seven, per the `AnalyzeAttachmentsTool` regression
  (`ak-dev-architecture`, Tools): the closures are defined as `read_kb`, `write_kb`, ... inside the
  factory, not as `_read_kb` bound to a differently-named `SystemTool`.

**[A2] Double-binding warning** (`design.md` decision 18). An application may add the `okf` block and
*also* bind a hand-built `KnowledgeBuilder` to the same agent, giving it two sets of identically named
tools.

- `Agent._attach_system_tools` (`core/base.py:530`) runs **after** the framework adapter has taken the
  already-built native agent — `OpenAIAgent.__init__` constructs, then attaches
  (`framework/openai/openai.py:366-376`) — so the manually bound tools are on the agent and visible
  when OKF attaches its own.
- `OKFToolFactory.get_tools` therefore compares the names it is about to attach against the names
  already present, and logs one `WARNING` naming the agent and the colliding tools when they overlap.
  It then **attaches anyway**.
- Attaching anyway is what keeps behavioural change 23's promise that no existing application changes:
  skipping would silently make a newly added `okf` block a no-op for that agent.
- The accepted cost: `Agent._append_tools` dedups by object identity only (`core/base.py:540`), so the
  duplicates reach the framework. Frameworks that tolerate duplicate names show the model the same
  tool twice; frameworks that reject them fail at bind time, with the warning explaining why rather
  than preventing it.
- Reading the existing names is done defensively (`getattr(native_agent, "tools", None) or []`), since
  not every adapter exposes a list-shaped `tools` attribute — a missing one means no warning, never a
  raise.

### Consumer changes

#### [A2] `OKFManager` (`okf/manager.py`)

- **`producer` -> `write_actor`** (`manager.py:106`, read at `manager.py:142` and stamped at
  `manager.py:793`; the `_default_producer()` static helper at `manager.py:835` becomes
  `_default_write_actor()`).
  - The parameter names the actor written into `generated.by` on a write, defaulting to
    `agentkernel/<version>`. It collides head-on with the `producer` **role** the amendment
    introduces — in the same class, where `OKFCapabilityManager` will construct instances from a
    block whose sibling key is also `producer`.
  - The role keeps the name because it is the user-facing concept; the constructor argument moves.
    In-tree no caller passes it (verified by grep over `ak-py/src`, `ak-py/tests`, `examples`), but it
    is a public constructor argument, so the rename is breaking for anyone who set it.
    Behavioural change 22.
  - `write_prefix` is untouched.
- No other change: the manager is constructed by `OKFCapabilityManager` with exactly the arguments the
  programmatic path already passes, and reads no config itself.

#### [A2] `core/config.py` — the `okf` block

```python
class _OKFDatabaseConfig(BaseModel):
    type: str = Field(description="Document store for this bundle: 'local', 's3', or a dotted path to a DocumentStore subclass")
    uri: str = Field(description="Bundle location passed to the resolved store: a filesystem path, an s3://bucket/prefix URI, or the store's own location string")
    description: Optional[str] = Field(default=None, description="Human-readable description of this bundle, surfaced to the agent in its instructions and through get_schemas")
    refresh_seconds: Optional[float] = Field(default=300.0, description="How stale the bundle manifest may get before the next operation re-walks the store; null disables automatic refresh")
    semantic_map: Optional[dict[str, str]] = Field(default=None, description="Placeholder tokens resolved to real bundle paths for this database only, e.g. {'<TABLES>': 'tables'}")
    consumer: list[str] = Field(default_factory=list, description="Agent names granted read access to this bundle")
    producer: list[str] = Field(default_factory=list, description="Agent names granted read and write access, instructed to add new knowledge to this bundle")
    curator: list[str] = Field(default_factory=list, description="Agent names granted read and write access, instructed to review and maintain existing knowledge in this bundle")


class _OKFConfig(BaseModel):
    databases: dict[str, _OKFDatabaseConfig] = Field(
        default_factory=dict,
        description="OKF bundles keyed by backend name; the key is what agents pass as the 'backend' argument to the knowledge-base tools",
    )
```

Added to `AKConfig` beside `schedule`, with the same `Optional`/presence-is-enablement shape:

```python
okf: Optional[_OKFConfig] = Field(
    default=None,
    description="Open Knowledge Format capability configuration (bundles and the agents that consume, produce, or curate them). Absent = the capability is disabled.",
)
```

- **No `enabled` flag**, per House Pattern 2: naming an agent in a role is the deliberate opt-in, and
  the block is meaningless without at least one. `thread` and `schedule` are the precedent.
- **No reuse candidate existed.** Checked against every model in `core/config.py`
  (`grep "class _" ak-py/src/agentkernel/core/config.py`): the store-selecting models
  (`_RedisConfig`, `_DynamoDBConfig`, ...) describe connections to a service, not a document-store
  URI plus per-bundle role lists. `_OKFDatabaseConfig` reuses nothing and subclasses nothing.
- **Every field has a named reader**: `type`/`uri` in `OKFCapabilityManager._resolve_store`,
  `description` in `OKFPromptComposer` and `OKFManager(description=...)`, `refresh_seconds` in
  `OKFManager(refresh_seconds=...)`, `semantic_map` in `KnowledgeBuilder(backend_semantic_maps=...)`,
  and the three role lists in `OKFRoleRegistry.from_config`.
- **`type` is redundant with `uri`'s scheme and kept anyway** — a stated departure from House Pattern
  2, carrying `design.md` decision 15. The redundancy is converted into a startup agreement check
  rather than a second source of truth. See [Deviations and additions](#deviations-and-additions) K.
- `AK_OKF__*` environment variables materialise the block exactly as `AK_THREAD__*` and
  `AK_SCHEDULE__*` do for theirs — so, as with those two, any such variable enables the capability.
  Unlike those two the result is inert rather than wrong: `databases` defaults to `{}`, no agent holds
  a role, and every agent gets no tools and no prompt.
- **Validation placement**: the two role rules and the store-agreement rule are enforced in
  `OKFRoleRegistry.from_config` / `OKFCapabilityManager._resolve_store`, not in pydantic validators,
  so the error text can name the database and the agents and so the config model stays a plain data
  carrier. `AKConfigError` is the type, matching every other backend-selection failure.

#### [A2] `core/tool.py` — one `SystemToolFactory` branch

```python
okf_config = getattr(AKConfig.get(), "okf", None)
if okf_config is not None:
    from ..knowledgebase.okf.tools import OKFToolFactory

    tools.extend(OKFToolFactory.get_tools(agent_name))
```

- Placed after the existing `schedule` branch in `get_all()`, so the OKF prompt section lands after the
  scheduling one in the concatenated suffix — deterministic ordering, which matters because the suffix
  is prompt text.
- **It does not call `_agent_allowed`.** That helper reads a flat `agents` list; OKF's scoping is
  per-`(agent, database)` and lives in `OKFRoleRegistry`. Passing `okf_config` to `_agent_allowed`
  would silently allow every agent, since the block has no `agents` attribute. This is the one
  capability whose filter is its own, and it is why the branch calls a factory that already takes
  `agent_name` rather than gating before the call.
- The lazy import inside the enabled-check is the sandbox/schedule precedent: `core/` never imports
  `knowledgebase/` at module scope, so the coupling rule holds and a process with no `okf` block never
  imports the KB tier.
- `OKFToolFactory.get_tools` calls `OKFCapabilityManager.get().validate_configuration()` once per
  process, so a malformed block fails at the first agent construction with an `AKConfigError` naming
  the database — not inside a tool call, and not at import.

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
  calling `_run(None, {})`. The skips are then **reported by raising `KnowledgeError` once the batch is
  through**: the writable records still land, but a write that stored nothing is no longer reported to
  the agent as a success — see behavioural change 17 and
  [Deviations and additions](#deviations-and-additions) H.

```python
stored, skipped = 0, 0
for record in records:
    meta = dict(record.get("metadata", {}))
    statement = meta.get("query") or meta.get("cypher_query")
    params = meta.get("params") or meta.get("cypher_params") or {}
    if not statement:
        log.warning("[neo4j.write] record carries no query; skipping. metadata keys=%s", sorted(meta))
        skipped += 1
        continue
    self._run(statement, params)
    stored += 1

if skipped:
    raise KnowledgeError(
        f"[KB][{self.backend_name}] {skipped} of {stored + skipped} record(s) carried no Cypher "
        f"and were not stored ({stored} stored). A Neo4j write needs the statement in "
        "metadata['query']."
    )
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
**[A2] The example becomes three agents driven by config.**

```
okf/
├── bundle/                     # unchanged, but writable: the store is constructed writable=True
├── config.yaml                 # NEW: the okf block naming the three agents
├── demo.py                     # REWRITTEN: three agents, no KB imports at all
└── demo_test.py                # EXTENDED: one ordered case per role
```

`config.yaml`:

```yaml
okf:
  databases:
    warehouse:
      type: local
      uri: ./bundle
      description: "Analytics warehouse concepts, one per table, in browsable namespaces."
      refresh_seconds: 300
      semantic_map:
        "<TABLES>": tables
      consumer: [KB_Consumer_Agent]
      producer: [KB_Producer_Agent]
      curator:  [KB_Curator_Agent]
```

- `demo.py` drops `LocalDocumentStore`, `OKFManager`, `KnowledgeBuilder`, `OpenAIToolBuilder`, and the
  whole `EXECUTION PROTOCOL` string (`demo.py:21-34`, `demo.py:45-72`, `demo.py:85`). What remains is
  three `Agent(...)` constructions with a description each, and `OpenAIModule([...])`. **No import
  from `agentkernel.knowledgebase` survives in the file** — that absence is the example's point, and
  `demo_test.py` asserts it.
- Agent names in `config.yaml` must match the `Agent(name=...)` values exactly; the README says so,
  because a typo yields an agent with no tools and no error.
- `demo_test.py` gains one ordered case per role: the consumer browses and answers citing a concept
  path; the producer writes a new concept and reads it back; the curator amends an existing one. A
  fourth case pins the refusal — the consumer attempting a write is told it is read-only.
- The bundle stays checked in and the store is writable, so the producer and curator write into
  `bundle/generated/`. Per `design.md` decision 16 the example prescribes no git-ignore or temp-copy
  handling; the generated directory is left for the developer to clear, and the README says so.
- The **programmatic** path keeps a home: the README's second section shows the original
  `LocalDocumentStore` -> `OKFManager` -> `KnowledgeBuilder` wiring for applications that want it, so
  the amendment adds a path rather than deleting the documented one.


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
**[A2] Additional documentation surfaces.** The table above stands; the amendment adds:

| Surface | Change |
|---|---|
| `docs/docs/advanced/knowledge-bases.md:47,484` | the "one `read_kb` tool serves every backend because `read()` routes" explanation is rewritten: the routing is the tool's, not the ABC's |
| same file, `:252` | `read_kb`'s description — "routed through `read()`" no longer true |
| same file, `:267` | the `search_kb` narrow-gate paragraph is replaced by the flat gate |
| same file, `:287` | semantic-map resolution gains the per-backend form |
| same file, `:490` | the capability/tool table's `search` row drops the "when `query` is declared too" qualifier |
| same file, new section | **the OKF config block**: the `okf` schema, the three roles, what each is granted, per-`(agent, database)` write enforcement, and the config-vs-programmatic choice |
| `docs/docs/core-concepts/overview.md:353` | the operation list drops `read` |

**[A2] Dev skills.** Two more surfaces beyond the two already named:

- `.agents/skills/ak-dev-new-knowledgebase-integration/SKILL.md:112-113,133,136,353` — the capability/tool
  matrix states `search_kb` needs `query` too, and lines 133 and 353 describe `read()`'s routing as a
  `KnowledgeBase` behavior. All four are now wrong.
- `.agents/skills/ak-dev-architecture/SKILL.md` — its Knowledge Bases section states *"`read()` is
  **concrete** and routes to `query()` when `query` is declared and `search()` otherwise"* and lists the
  `search_kb` gate as "one backend declares **both** `search` and `query` — a per-backend check no
  built-in satisfies". Both sentences are invalidated, and the section gains the `okf` config block and
  the role layer.
- `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:376,408,414` — the `build()` output list and
  the read-only guidance; `build()` can now return three to seven callables.


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

**Superseded by [A2].** The original text read, in full: *"None. No `AKConfig` section is added
(design decision 1), no field is renamed, and no `AK_*` environment variable gains or loses meaning."*
That held for the representation/capability/storage work and no longer holds for the role layer.

**[A2] One new optional block, `okf`**, specified in full under
[`core/config.py` — the `okf` block](#a2-coreconfigpy--the-okf-block). Summarised for compatibility
review:

- **Added**: `AKConfig.okf: Optional[_OKFConfig] = None`, and the two models `_OKFConfig` /
  `_OKFDatabaseConfig`.
- **Renamed**: nothing in `AKConfig`.
- **Removed**: nothing.
- **Existing YAML and `AK_*` variables**: unchanged in meaning and unchanged in effect. A config file
  written before this change parses identically and produces an `okf` of `None`, which disables the
  layer entirely — no agent gains a tool or a prompt line.
- **New env vars**: `AK_OKF__DATABASES__<NAME>__*` follow the standard `AK_`/`__` nesting. Setting any
  of them materialises the block, as with `thread` and `schedule`; unlike those two the outcome is
  inert rather than surprising, because a materialised block with no databases grants nothing.
- **Field descriptions** surface in generated config docs, so each one is written as user-facing text.
- Backends remain application-constructible with no config present: `DocumentStore.from_uri` plus a
  hand-built `OKFManager` and `KnowledgeBuilder` is untouched and still the only path for Chroma,
  Neo4j, Starburst, and bring-your-own backends.

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

Items 1-13 are `design.md`'s list, restated only where this spec fixes a detail; 14-17 are new and are
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
    neither, with a warning. The batch then **raises `KnowledgeError`** naming what was stored and what
    was not — see item 17.
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
17. **A text-only Neo4j `write_kb` now reports a failure.** `Neo4jManager.write` raises
    `KnowledgeError` after the batch when any record carried no Cypher, so
    `write_kb("neo4j", text="…")` with no query surfaces "Failed to write…" rather than "Stored
    successfully" for a write that stored nothing. Prompt-visible, and deliberate: on `develop` such a
    write also failed, but only because `_run(None, {})` happened to error — item 12's skip would have
    turned that failure into a silent success. Pinned by
    `test_the_skip_report_names_what_was_stored_and_what_was_not`; see
    [Deviations and additions](#deviations-and-additions) H.

**[A2] Items 18-25**, tracing `design.md`'s amended list. Each needs a test.

18. **`KnowledgeBase.read()` is removed.** A public method on a public ABC disappears. `read_kb` keeps
    its name, signature and routing, so no agent-visible behavior changes. A third-party subclass that
    overrode `read()` keeps the method but nothing calls it; to stay reachable it must declare and
    implement `search` or `query`. This **supersedes item 1**: the `read`->`search`/`query` renames on
    the three backends stand, but there is no base alias behind them, so item 1's "a third-party
    subclass overriding `read()` keeps winning" no longer holds.
19. **`search_kb` is emitted whenever any backend declares `search`.** Every Chroma and OKF deployment
    gains a tool it did not have, which is prompt-visible. For a search-only backend `read_kb` and
    `search_kb` now reach the same `search()` call; both docstrings are rewritten so the distinction
    they state is the one that exists. **Supersedes** the narrow-gate half of item 7.
20. **`build()` takes `writable: bool = True`.** Default behavior is byte-identical, including tool
    order. `build(writable=False)` omits `write_kb` entirely rather than emitting it to refuse per
    call.
21. **`KnowledgeBuilder.__init__` takes `backend_semantic_maps`.** Additive third parameter; the flat
    `semantic_map` keeps its meaning and position. **Narrows** the original Non-changes assertion that
    froze the `(backends, semantic_map)` signature.
22. **`OKFManager.__init__`'s `producer` parameter is renamed `write_actor`.** Breaking for any caller
    that set it; none in-tree. The `generated.by` value it produces is unchanged, so bundles written
    before and after are byte-identical for the same actor.
23. **An `okf` block binds tools and appends a prompt section to named agents.** For an application
    that adds the block, the named agents gain up to seven tools and a prompt section they did not
    have. For every application without the block, `AKConfig.okf` is `None` and nothing changes —
    including no import of the knowledge-base tier.
24. **A consumer-role agent calling `write_kb` on a database it may not write gets a refusal string**
    naming the databases it may write to, rather than a successful write or an exception. This is new
    behavior with no predecessor: before the amendment there was no notion of an agent lacking write
    permission on a writable backend.
25. **`get_schemas` and `get_all_kb_descriptions` list only the calling agent's databases** on the
    config path, because its builder holds only those. On the programmatic path they list every
    registered backend, exactly as today.

**[A2] Non-changes, amended.** Three entries of the original list above no longer hold and are
superseded by items 18, 21 and 23 respectively: the `read` signature, `KnowledgeBuilder.__init__`'s
signature, and "No `AKConfig` section". Two more are narrowed rather than withdrawn: *"every existing
example under `examples/cli/knowledgebase/openai/` runs unmodified"* now excludes the OKF example,
which this amendment rewrites (the other three are unaffected and asserted so); and *"the four
existing tool names and signatures"* holds — `read_kb`'s name, signature, and behavior are all
unchanged, only its implementation moved. Everything else in the original list stands, and gains:

- `write_kb`'s per-call `writable` capability check, its validation strings, and its record shape.
- The programmatic path: `OKFManager` + `KnowledgeBuilder` + a framework `ToolBuilder` with no `okf`
  block present behaves exactly as it does after the unamended change.
- `OKFManager.write_prefix`, `max_concepts`, and every other constructor argument but `producer`.
- No framework adapter change, and no new optional extra — `pyyaml` is core and the `aws` extra
  already covers `s3://`.

**Non-changes, to be asserted (original list):**

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
| `tests/test_knowledgebase_okf_manager.py` | capabilities built from the store (writable folding both ways); `_derived_schema()` keys against a known bundle; `schema()` working with no `add_schema()`; search ranking — weights, presence-not-frequency, `(-score, path)` determinism across two managers, zero-score exclusion; `fetch` order/dedup/unknown-id omission and links present only here; `browse` index-vs-derived at root **and** at `tables/`, `limit` truncation, unknown directory; `write` — synthesised vs supplied id, comma refusal at both ends, fixed key order and byte-identical re-render, `generated` stamp, producer default and override; **write-through visibility with `refresh_seconds=None`** (proving it is not a refresh) and a refresh landing mid-write not discarding it; the schema's `top_level_directories` agreeing with the root listing over a directory holding only an `index.md`; refresh timing with a monkeypatched `time.monotonic`; a failed refresh serving the stale manifest and resetting the clock; `reload()`; **one walk under two concurrent boundary-crossing callers** (a `threading.Barrier` plus a walk counter); `max_concepts` truncation keeping a lexicographic prefix with a `truncated` diagnostic; nothing filtered on trust or staleness; diagnostics surfaced through `get_description()` |
| `tests/test_knowledgebase_okf_envelope.py` | the declared scale. A session-scoped fixture generates a 10,000-concept bundle in `tmp_path`; the test asserts the walk keeps all 10,000, that every concept's body index sits at the cap, that ranking is deterministic, and that `max_concepts` truncates to a lexicographic prefix with a diagnostic. Memory is measured as the sum of `size_diff` over a `snapshot_after.compare_to(snapshot_before, "filename")` around `_walk()` — **not** process RSS, which moves with the interpreter and the allocator's retained arenas — and asserted **per concept** against a 25 KB budget (250 MB projected at 10,000), because the cost is linear in the concept count and the per-concept figure is what stays true at every size. The measurement runs over a 2,000-concept slice: `tracemalloc` around a full 10,000-concept walk costs 75 s under coverage to learn the same number |
| `tests/test_knowledgebase_contract.py` | `KnowledgeBaseContract` run against `FakeKnowledgeBase` (four capability shapes), `OKFManager` over a real local bundle, and the three existing backends with mocked clients — `monkeypatch` on `chromadb.PersistentClient`, `neo4j.GraphDatabase.driver`, and `trino.dbapi.connect` (plus host/user/password constructor args for Starburst) |
| `tests/test_knowledgebase_exports.py` | every `__all__` name resolves; `chromadb`/`neo4j`/`trino`/`boto3` stay out of `sys.modules` after importing the package and touching `KnowledgeBase`/`OKFManager`; no contract suite is exported; the `overview.md:353` import works verbatim |
| `examples/cli/knowledgebase/openai/okf/demo_test.py` | the example-level convention (`Test("demo.py")`, ordered cases): the agent browses the bundle, fetches a concept by its real path, and answers from it |

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

### [A2] Amended testing

**Superseded by [A2]**: *"No existing test file changes."* That was true when the knowledge-base tier
had no tests; the unamended change added ten test files, and this amendment moves assertions in four
of them. The patch targets that move are named below, per the plan's requirement.

#### Existing assertions that move or invert

| File | Assertion | What happens |
|---|---|---|
| `knowledgebase/testing.py:661` | `test_contract_read_routes_on_the_declaration` | **Deleted from the contract.** The rule it pins is no longer a backend obligation; the same assertion is re-established at the tool layer in `test_knowledgebase_builder.py` |
| `knowledgebase/testing.py:682` | `test_contract_read_returns_records_through_the_real_operation` | Rewritten to call `query()`/`search()` directly on the declaration instead of `read()` |
| `knowledgebase/testing.py:698` | `test_contract_format_results_renders_the_rows_the_backend_produced` | Same rewrite — it reaches rows through `read()` today |
| `tests/test_knowledgebase_base.py:87,92` | `test_read_routes_to_query_for_a_query_backend`, `..._to_search_for_a_non_query_backend` | **Moved** to `test_knowledgebase_builder.py` and restated against `read_kb` |
| `tests/test_knowledgebase_base.py:97` | `test_read_forwards_limit_and_kwargs_unchanged` | **Deleted.** `read_kb` takes no `**kwargs`, so there is nothing to forward; the `limit` half moves with the two above |
| `tests/test_knowledgebase_base.py:105` | `test_read_defaults_to_a_limit_of_three` | **Moved** — the default now belongs to `read_kb`'s signature |
| `tests/test_knowledgebase_base.py:110` | `test_a_subclass_overriding_read_still_wins` | **Replaced** by `test_the_abc_exposes_no_read_method` (`not hasattr(KnowledgeBase, "read")`), which is the guard that the removal stays removed |
| `tests/test_knowledgebase_builder.py:136` | `test_search_and_query_on_different_backends_does_not_emit_search_kb` | **Inverted** and renamed: `search_kb` is now emitted whenever any backend declares `search`, regardless of where `query` lives |
| `tests/test_knowledgebase_okf_manager.py:431,454,471,529` | four `OKFManager(..., producer="process:demo")` constructions | Renamed to `write_actor="process:demo"` — the only in-tree callers of the parameter |

#### New assertions in existing files

| File | Adds |
|---|---|
| `tests/test_knowledgebase_base.py` | the ABC exposes no `read`; a backend declaring only `browse` still constructs and its `search`/`query` still raise `KnowledgeCapabilityError` |
| `tests/test_knowledgebase_builder.py` | **still the riskiest consumer.** `read_kb` routing on `capabilities.query` (both directions) and its `limit` default; the neither-`search`-nor-`query` guard string; `search_kb` emitted for a search-only backend; `build(writable=False)` omitting `write_kb` while `build()` keeps all four in their historical order; `backend_semantic_maps` resolving per backend, a per-backend entry beating the flat map for that backend only, and an entry naming an unheld backend warning rather than raising |

#### New test files

| File | Asserts |
|---|---|
| `tests/test_knowledgebase_okf_roles.py` | `OKFRoleRegistry.from_config` over literal dicts: agent -> assignments for the single-role, multi-database, and different-role-per-database cases; `may_write` true for producer and curator and false for consumer; `writable_databases_for` returning only the writable subset; `has_any_role` false for an unnamed agent; and both `AKConfigError`s — a database with three empty lists, and one agent listed as both `producer` and `curator` of the same database — each naming the database. Plus the negative: the same agent as `producer` of one database and `curator` of another is **accepted** |
| `tests/test_knowledgebase_okf_config.py` | `_OKFConfig` parsing from YAML and from `AK_OKF__*` env vars; `AKConfig.okf` defaulting to `None` and a pre-change config file parsing unchanged; `refresh_seconds: null` surviving as `None`; every field's default; `OKFCapabilityManager._resolve_store`'s three branches and both agreement failures (`type: local` with an `s3://` uri, `type: s3` without one), each naming the database, type and uri; a dotted-path `type` resolving through `resolve_dotted`; and an unknown short name raising `AKConfigError` |
| `tests/test_knowledgebase_okf_tools.py` | the agent surface end to end over a real local bundle. `OKFToolFactory.get_tools` returning `[]` for an unnamed agent, six tools for a consumer, seven for a producer/curator; `SystemToolFactory.get_all("<name>")` including them only when the block is present, and `get_system_prompt_suffix` carrying the role mandate for the right agent and nothing for an unnamed one; `func.__name__ == SystemTool.name` for all seven (the `AnalyzeAttachmentsTool` regression guard); a consumer's `write_kb` returning the refusal string naming its writable databases, and a producer's succeeding against the same bundle; an agent's `read_kb` at a database it holds no role in returning `KnowledgeBuilder`'s unknown-backend string; `get_schemas` listing only that agent's databases; one `OKFManager` shared by two agents over the same database (a walk counter); no store walk performed during `get_tools` (the laziness guarantee); `validate_configuration` **warning, not raise**, for a read-only store under a `producer`, with the message naming the database and the agents (`caplog`); and the **double-binding warning** — an agent already carrying a `read_kb` gets one WARNING naming it and the colliding names, and still receives OKF's tools, plus the defensive case where the native agent exposes no `tools` attribute and no warning is emitted |
| `tests/test_knowledgebase_okf_prompts.py` | `OKFPromptComposer.compose` from config alone with **no backend constructed**: the per-database line carrying name, description and read-vs-read-and-write; both mandates present for an agent holding different roles in two databases; `''` for an agent with no role; and the navigation protocol present exactly once regardless of database count |

#### Test-infrastructure notes

- `OKFCapabilityManager.reset()` is called from an `autouse` fixture in every new file, the
  `ScheduleManager.reset()` / `ThreadRunner.shutdown_event.clear()` precedent: a process-wide singleton
  left populated by one test silently changes the next.
- Config is supplied by monkeypatching `AKConfig.get` to a fake carrying an `okf` attribute — the
  convention in `ak-dev-testing-conventions`. The `core/tool.py` branch uses `getattr(..., "okf",
  None)`, so a fake without the attribute exercises the disabled path.
- No test constructs an `S3DocumentStore`; the `s3` branch is asserted through `_resolve_store`'s
  agreement checks and a monkeypatched `from_uri`, keeping the suite offline.

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
| I | **`write()` applies its write-through under `_refresh_lock`**, rather than accepting a dropped-write race | The design and this spec first documented a write landing mid-refresh as dropped from the manifest until the next walk. An agent that writes a concept and immediately searches for it would then be told its own write does not exist — indistinguishable, from the agent's side, from a failed write. Taking the lock costs `write()` a wait of up to one refresh walk (over S3, one `list_objects_v2` pagination plus a ranged GET per concept); paying it on the rare writing path is cheaper than an agent-visible lie |
| H | **`Neo4jManager.write` raises `KnowledgeError` after a batch that skipped records** (item 17), rather than only logging the skip | The design has the skip keep the rest of the batch running but leaves the agent-facing result unstated. Logging alone would report a write that stored nothing as a success — strictly worse than pre-#553, where `_run(None, {})` at least errored. Raising after the loop keeps both intents: the writable records land, and the tool layer reports the truth |
| J | **[A2] A read-only store under a `producer`/`curator` role warns rather than raising** | Resolved as `design.md` decision 19. Recorded here because it is the one validation in the block that does not raise, and a reviewer applying the section's own rules mechanically will ask why: the other checks are on config text, this one is on the environment, and the same file is legitimately correct where the bundle happens to be read-only. The residual cost — a missed warning leaves an agent instructed to write and refused every time — is accepted, not overlooked |
| K | **[A2] `type` duplicates what `uri`'s scheme already encodes** | Carrying `design.md` decision 15, and a stated departure from House Pattern 2 (reuse existing configuration; do not add a duplicate `type` selector). The redundancy is made safe by the agreement check rather than left as two sources of truth. Recorded here because a reviewer applying the house rules mechanically will flag it |
| M | **[A2] Double-binding is detected and warned, not prevented** | Resolved as `design.md` decision 18. `OKFToolFactory.get_tools` warns on a name collision and attaches anyway, so a config-plus-manual agent still reaches its framework with duplicate tool names — an error on the frameworks that reject them. Recorded because it is a known-and-accepted failure mode rather than an oversight: preventing it would make a newly added `okf` block silently do nothing for that agent, which is the worse of the two. Switching to skip-and-warn is confined to this one method |
| L | **[A2] `OKFToolFactory` closures capture the agent name; the calling agent is re-resolved at call time anyway** | Belt and braces, and not redundant: the closure's name is what decides *which* tools were attached, while `ToolContext` is what proves *who* is calling when the write refusal is issued. They agree in every normal case; the re-resolution is what keeps the refusal honest if a tool object is ever shared between agents by a future framework adapter |

## Next stage

`plan.md` (stage 3) orders this into iterations. **[A2]** It is amended in the same pass as this
document: iterations 10-13 carry the role layer, and iteration 9 (docs and skills) grows the surfaces
listed above.
