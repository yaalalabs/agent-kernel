# #553: Open Knowledge Format support and the knowledge-base architecture refactor

Splits the knowledge-base layer along three independent axes — **representation** (what the knowledge
*is*), **capability** (what a backend can *do* with it), and **storage** (where the bytes *live*) —
then adds Open Knowledge Format as the first representation that exercises all three: an OKF bundle
is parsed by format code that knows nothing about storage, served over a `DocumentStore` that knows
nothing about OKF, and exposed to agents through the same `KnowledgeBuilder` tools every other
backend uses. The one-sentence design idea: **a backend's shape becomes declared data
(`KnowledgeCapabilities`), not a class hierarchy**, so the KB tier can grow new kinds of knowledge
without growing new abstract base classes.

Supporting research: [`research/okf-format-survey.md`](research/okf-format-survey.md) — what OKF is,
what it binds a consumer to, and which of its properties drive the decisions below.

## Motivation

### The current contract has one retrieval hole, and OKF needs three

- `KnowledgeBase` exposes exactly one retrieval operation, `read(query, limit)` (`base.py:84`), so
  every backend must express its whole retrieval surface as one string.
  - Chroma treats it as a semantic query (`chroma.py:111`), Neo4j as Cypher (`neo4j.py:138-143`),
    Starburst as SQL (`starburst.py:184`). Three unrelated languages behind one signature, with
    nothing on the object saying which.
  - OKF's identity *is* the file path (`research/okf-format-survey.md` §2), so an agent must be able
    to **fetch by id** and **browse a namespace**. Neither is expressible as `read(query)`.
- There is no machine-readable statement of what a backend supports. The constraints exist, but only
  as prose in a hand-written schema dict (`examples/cli/knowledgebase/openai/starburst/demo.py:49-52`
  declares `"write_supported": false` as free text the runtime never reads) and as inconsistent
  runtime failures:
  - `StarburstManager.write` raises `NotImplementedError` (`starburst.py:141`).
  - `StarburstManager.read` returns `[]` for a rejected statement (`starburst.py:178`) and `[]` again
    for a genuine query failure (`starburst.py:227`) — indistinguishable from "no results".
  - `ChromaManager` and `Neo4jManager` accept writes with no declared constraint at all.

### The router leaks one backend's dialect into the shared tool

- `KnowledgeBuilder.write_kb` writes Neo4j-specific metadata keys for **every** backend: on every
  write **that carries a query**, it sets `cypher_query` and `cypher_params` alongside the generic
  `query`/`params` (`knowledgebuilder.py:155-167`, the whole block guarded by `if resolved_query:`),
  because `Neo4jManager.write` reads only the `cypher_*` spelling (`neo4j.py:120-121`). A
  query-carrying Chroma write therefore stores dead Cypher keys in its metadata; a text-only write —
  the common Chroma case — stores `{"source": ...}` alone and is unaffected.
- `get_schemas` calls `backend.schema()` for every backend inside one `json.dumps`
  (`knowledgebuilder.py:105`) with no per-backend guard — while its sibling
  `get_all_kb_descriptions` does guard each backend (`knowledgebuilder.py:185-187`). Since
  `schema()` raises `ValueError` when `add_schema()` was never called (`base.py:57-58`), one
  unconfigured backend makes the agent's first tool call raise into the framework.
- **`StarburstManager.schema` shadows the base `schema()` method**, so `get_schemas` is broken today
  for every Starburst deployment — not only unconfigured ones.
  - `__init__` assigns the Trino schema name to the same attribute (`self.schema = schema`,
    `starburst.py:67`) that `KnowledgeBase` defines as a method (`base.py:50`). The instance
    attribute wins, so `backend.schema()` at `knowledgebuilder.py:105` raises
    `TypeError: 'str' object is not callable`.
  - This fires even though the example does call `.add_schema(...)`
    (`examples/cli/knowledgebase/openai/starburst/demo.py:30`) — the configured schema is stored in
    `_dynamic_schema` and is unreachable for the life of the object.
  - Consequence for this change: adding `"capabilities"` to `schema()` output cannot reach Starburst,
    and the per-backend `try/except` below would *mask* the collision as an error string rather than
    fix it. The attribute must be renamed.

### Schemas must be hand-written, but OKF bundles carry their own

- `schema()` returns only what the application passed to `add_schema()`, merged under
  `{"backend": name}` (`base.py:60-62`), and hard-fails when nothing was passed (`base.py:57-58`).
- An OKF bundle already declares its own concept types, index, and version
  (`research/okf-format-survey.md` §3, §6). Requiring a deployment to hand-transcribe that into a
  dict would guarantee drift between the bundle and what the agent is told about it.

### Record and result shapes cannot carry OKF's provenance

- `Record` is `Mapping[str, Any]` (`base.py:4`) and the default `format_results` renders only
  `text` plus `metadata["source"]` (`base.py:103`).
- OKF's load-bearing fields — path identity, `type`, trust tier, `stale_after`, `sources[]` — have
  nowhere to go that survives to the agent (`research/okf-format-survey.md` §3).

### The package is not importable the way it is documented

- `knowledgebase/__init__.py` is a single comment line and exports nothing, while
  `docs/docs/core-concepts/overview.md:353` documents `from agentkernel.knowledgebase import
  KnowledgeBase`. That import fails today.
- There are no tests for the knowledge-base tier anywhere under `ak-py/tests/` (the suite has files
  for every other pluggable tier), so nothing pins the contract this change refactors.

### The house patterns this change should have been using already exist

- Honest per-backend capability declaration plus optional operations that raise a typed error:
  `SandboxCapabilities` (`sandbox/model.py:33-48`) and `Sandbox.execute_command` /
  `upload_file` defaulting to `SandboxCapabilityError` (`sandbox/base.py:39-69`).
- Backend-selection factories: `resolve_dotted` / `require_extra` / `AKConfigError`
  (`core/util/factory.py:18,26,50`).
- Reusable conformance suites for pluggable tiers: `SandboxProviderContract`
  (`sandbox/testing.py:130`) and `QueueTransportContract` (`pipeline/testing.py`).
- Lazy public exports that keep optional dependencies optional: the PEP 562 `__getattr__` map in
  `deployment/aws/__init__.py` behind `agentkernel/aws.py`.
- Refusing to fetch remote references from inside a framework component, for SSRF reasons:
  `core/multimodal/hooks.py:41,344`.

## Design shape

Three axes, each replaceable without touching the other two:

| Axis | Question | Owns | Knows nothing about |
|---|---|---|---|
| **Representation** | What is this knowledge? | `OKFBundle` / `OKFConcept` parsing, frontmatter families, links, trust tiers | where bytes come from |
| **Capability** | What can I do with it? | `KnowledgeCapabilities`, the operation set, `KnowledgeCapabilityError` | any specific backend |
| **Storage** | Where are the bytes? | `DocumentStore`: `LocalDocumentStore`, `S3DocumentStore` | markdown, YAML, OKF |

```mermaid
classDiagram
    class KnowledgeBase {
        <<abstract>>
        +backend_name
        +capabilities : KnowledgeCapabilities
        +schema()
        +search(query, limit)
        +query(statement, limit)
        +fetch(ids)
        +browse(path, limit)
        +write(records)
        +read(query, limit) "routes to query/search"
    }
    class KnowledgeCapabilities {
        +kinds
        +search / search_mode
        +query / query_language
        +fetch / browse / writable
        +derives_schema
    }
    class DocumentKnowledgeBase {
        <<abstract>>
        path-addressed documents
    }
    class DocumentStore {
        <<abstract>>
        +read_bytes(path)
        +list(prefix)
        +exists(path)
        +write_bytes(path, data)
    }
    KnowledgeBase --> KnowledgeCapabilities : declares
    KnowledgeBase <|-- ChromaManager
    KnowledgeBase <|-- Neo4jManager
    KnowledgeBase <|-- StarburstManager
    KnowledgeBase <|-- DocumentKnowledgeBase
    DocumentKnowledgeBase <|-- OKFManager
    DocumentKnowledgeBase o-- DocumentStore
    DocumentStore <|-- LocalDocumentStore
    DocumentStore <|-- S3DocumentStore
    OKFManager ..> OKFBundle : parses via
    OKFBundle *-- OKFConcept
```

## Requirements

### Capability declaration

- Add `KnowledgeCapabilities` (pydantic `BaseModel`, `knowledgebase/model.py`), mirroring the shape
  of `SandboxCapabilities` (`sandbox/model.py:33-49`).
  - `kinds: list[str]` — advisory taxonomy surfaced to the agent, an **open list** whose conventional
    values are `vector`, `structured`, `graph`, `document`; an out-of-tree backend may declare its own
    kind without a framework release, and unknown values reach the agent unchanged. A backend may
    declare more than one (Neo4j declares `["graph", "structured"]`).
  - `search: bool` and `search_mode: "semantic" | "lexical" | None` — relevance retrieval, and
    honestly which kind. Chroma is `semantic`; OKF is `lexical`.
  - `query: bool` and `query_language: str | None` — e.g. `"cypher"`, `"sql"`. The two move
    together: `query=True` requires a non-empty `query_language`, and `query=False` requires
    `query_language=None` (the bidirectional invariant below).
  - `fetch: bool` — retrieval by identity.
  - `browse: bool` — enumeration of the backend's namespace.
  - `writable: bool`.
  - `derives_schema: bool` — whether `schema()` can self-describe without `add_schema()`.
- Declared as an **instance attribute** set in each backend's `__init__` (`self.capabilities = ...`),
  **not** a `ClassVar` — a deliberate divergence from `Sandbox.capabilities` (`sandbox/base.py:88`),
  where a provider's shape is fixed by its class.
  - A KB's shape depends on what it was constructed with: `OKFManager.capabilities.writable` folds in
    `store.writable`, which differs between a `LocalDocumentStore` and an `S3DocumentStore` over a
    read-only prefix. A `ClassVar` cannot express that.
  - `KnowledgeBase.__init__(capabilities, name=None)` takes the capabilities object and validates the
    invariants below; every subclass calls `super().__init__(capabilities=..., name=...)`. The base
    declares `capabilities: KnowledgeCapabilities` as a bare annotation for typing, with no
    class-level default.
  - The `name` argument exists **so the validation error can name the backend**. `backend_name` stays
    an abstract property and is *not* readable during base-class validation: subclasses assign what it
    reads only after `super().__init__()` — `StarburstManager` calls `super().__init__()` at
    `starburst.py:60` and assigns `self.name` at `starburst.py:69`, while `backend_name` reads
    `self.name` (`starburst.py:82`). Touching `self.backend_name` from the base `__init__` would raise
    `AttributeError`, not the promised `ValueError`, so validation uses `name or type(self).__name__`
    and never reads the property.
- Declared values must be true of the instance: a backend declaring `fetch=True` must override
  `fetch()`. Verified by the contract suite (below), not by trust.
- **Invariants, enforced at construction** — each violation raises `ValueError` naming the backend
  (from the `name` argument above, falling back to the class name):
  - **Reachability**: at least one of `search`, `query`, `fetch`, `browse`, or `writable` is `True`.
    - The bar is "reachable through *some* tool", not "reachable through `read_kb`" — a write-only
      sink (an append-only audit or event log an agent records into but never reads back) is a
      legitimate backend, and so is a browse-only catalogue.
    - A backend with no read capability at all is still registrable; `read_kb` routed at it returns
      the actionable capability string, exactly as any other undeclared operation does.
  - **Query coherence**: `query_language` is non-empty **iff** `query` is `True`. Bidirectional, so a
    backend cannot declare a query language it does not serve, and `capabilities.query` alone decides
    the `read()` route below.
- Declaring `kinds` as data — rather than as `VectorKB` / `StructuredKB` / `FileSystemKB` base
  classes — is the load-bearing choice; see [Deviations from the proposed class
  diagram](#deviations-from-the-proposed-class-diagram).

### Operation set on `KnowledgeBase`

- Retain the existing abstract members unchanged: `backend_name`, `connect()`, `get_description()`,
  and the provided `add_schema()` / `format_results()` / `close()`.
- Five operations — four retrieval plus `write` — each **optional**, with a base implementation that
  raises `KnowledgeCapabilityError(backend_name, operation)` — the `sandbox/base.py:39-69` shape:

  | Operation | Signature | Declared by |
  |---|---|---|
  | `search` | `(query: str, limit: int = 3, **kwargs) -> list[Record]` | `capabilities.search` |
  | `query` | `(statement: str, limit: int = 3, **kwargs) -> list[Record]` | `capabilities.query` |
  | `fetch` | `(ids: list[str], **kwargs) -> list[Record]` | `capabilities.fetch` |
  | `browse` | `(path: str = "", limit: int = 50, **kwargs) -> list[Record]` | `capabilities.browse` |
  | `write` | `(records: Iterable[Record], **kwargs) -> None` | `capabilities.writable` |

- **Every operation keeps `**kwargs`**, matching today's `read`/`write` (`base.py:74,84`) and all three
  backends (`chroma.py:102`, `neo4j.py:125`, `starburst.py`), which already accept and ignore it.
  - `read()` forwards its `**kwargs` unchanged to whichever primitive it delegates to, so a caller
    passing backend-specific options through `read()` reaches the same code it reaches today.
  - Dropping `**kwargs` on the read path would be a signature change; the **Non-changes** assertion
    below covers it.
- `read(query, limit, **kwargs)` becomes a **concrete** method on the base that delegates to `query()`
  when `capabilities.query` is `True`, else to `search()`. **This is the one statement of the routing
  rule**; every other mention in this document refers back to it.
  - Gating on the boolean rather than on `query_language` is what makes the rule total. With the
    bidirectional invariant the two can no longer disagree, so a backend declaring `search` but not
    `query` can never be routed at a `query()` that raises `KnowledgeCapabilityError`.
  - Keeps `read_kb` and every external caller working with no signature change.
  - A subclass that still overrides `read()` — including any application's own backend — keeps
    winning, so **for the read path** bring-your-own backends written against today's ABC need no
    edit. The `__init__` signature change still reaches them: see migration item 13.
  - When a backend declares **both** `search` and `query`, `read()` routes to `query()` and the
    relevance path is reached through `search_kb` instead (see [Agent surface](#agent-surface--knowledgebuilder)).
  - Renaming `Neo4jManager.read` to `query` moves its default from `limit=10` (`neo4j.py:125`) to the
    base's `limit=3`. `read_kb` always passes `limit` explicitly, so only a direct
    `neo4j.read(q)` call sees the change; it is listed as a behavioural change below.
- Add `knowledgebase/errors.py` with `KnowledgeError` and `KnowledgeCapabilityError`, matching
  `sandbox/errors.py`. `KnowledgeCapabilityError` replaces `StarburstManager`'s ad-hoc
  `NotImplementedError` (`starburst.py:141`).

### Records and result formatting

- `Record` stays `Mapping[str, Any]` (`base.py:4`) — no runtime shape change, so no existing backend
  or user subclass is invalidated.
- Add **two** `TypedDict`s (`total=False`) so the two levels of a record are named separately — today
  the shape `{"text": ..., "metadata": {...}}` is only a convention held in each backend's code:
  - `KnowledgeMetadata` — the **reserved keys inside `metadata`**:
    - `id` — the backend-native identity (an OKF bundle path). Required in the `metadata` of any
      record a `fetch`-capable backend returns, because it is what the agent passes back to `fetch`.
    - `source`, `title`, `kind`, `trust`, `stale`, `links`.
  - `KnowledgeRecord` — the **whole record**: `text: str` and `metadata: KnowledgeMetadata`.
  - Both are documentation-only: `Record` remains the runtime type on every signature, so neither is
    validated and neither invalidates an existing backend.
  - Unknown keys at **either** level are carried through untouched — asserted by the contract suite.
- `format_results` (`base.py:94-103`) gains an `id` prefix, **gated on the backend declaring
  `fetch`** — not merely on `metadata["id"]` being present:
  - Rendered as `- [<id>] <text> (source: <source>)` when `capabilities.fetch` is `True` and
    `metadata["id"]` is a non-empty string; the existing
    `- <text> (source: <source>)` line (`base.py:103`) is produced in every other case, byte for byte.
  - The gate exists because `metadata` is caller-supplied for the existing backends — a Chroma
    deployment may already store an `id` key of its own, and an ungated prefix would silently change
    the text those agents see. Chroma, Neo4j, and Starburst all declare `fetch=False`, so their output
    is unchanged; it is listed as a behavioural change below regardless, because it is prompt-visible
    for any backend that later declares `fetch`.
  - A missing, empty, or non-string `id` on a `fetch`-capable backend degrades to the unprefixed line
    rather than rendering `[None]`.
  - Backends may override; `OKFManager` does.

### Schema derivation

- `schema()` gains a `_derived_schema() -> Mapping[str, Any]` hook, defaulting to `{}`.
  - Final schema = `{"backend": name}` + `_derived_schema()` + `_dynamic_schema`, in that order —
    an explicit `add_schema()` value always wins over a derived one.
  - Also add `"capabilities": capabilities.model_dump()` so the agent is told what the backend can do
    from the same call it already makes.
- The hard failure at `base.py:57-58` is relaxed: it raises only when **both** `_dynamic_schema` and
  `_derived_schema()` are empty. The unconditional `{"backend": name}` and `"capabilities"` entries
  never count as content — otherwise the guard could never fire again. A backend that self-describes
  needs no `add_schema()`; a backend that neither derives nor was configured still fails loudly,
  exactly as today.
  - `capabilities.derives_schema` is a declaration, not the gate: it tells the agent that
    `_derived_schema()` is expected to be non-empty, and `KnowledgeBaseContract` fails a backend that
    declares it while returning `{}` rather than letting it serve a content-free schema.
- `OKFManager._derived_schema()` returns the bundle's own `okf_version`, the distinct `type` values
  present, the top-level directory names, concept count, and the reserved-file inventory — read from
  the loaded bundle, never hand-transcribed.
- **`StarburstManager`'s attribute/method collision is fixed** so that `schema()` is reachable at all:
  the Trino schema name moves to `self.db_schema` (`starburst.py:67`, with its readers at
  `starburst.py:111,116,204`).
  - The constructor keyword stays `schema=`, so both existing call sites that pass it
    (`examples/cli/knowledgebase/openai/starburst/demo.py:22`, `.../multi/demo.py:99`) are unchanged.
  - `KnowledgeBaseContract` asserts that `schema()` is callable and returns a mapping on every
    backend, so no future backend can reintroduce the collision with a same-named attribute.

### Storage layer — `DocumentStore`

- New `knowledgebase/store/` package. `DocumentStore` is an ABC over a path namespace, with **no
  knowledge of markdown, YAML, or OKF**:
  - `read_bytes(path) -> bytes`, `exists(path) -> bool`, `list(prefix: str = "") -> list[str]`,
    `write_bytes(path, data) -> None`, `close() -> None`.
  - `writable: bool` property — `S3DocumentStore` over a read-only prefix declares `False`, and the
    KB above it folds that into `capabilities.writable`.
  - Paths are POSIX-style and **bundle-relative**; the store owns the mapping to a filesystem path or
    an object key.
  - **The store owns containment.** Every path it accepts or emits — through `read_bytes`, `exists`,
    `write_bytes`, and every entry `list()` returns — is normalised and confined to the store's own
    namespace; one that escapes is refused, never resolved. Containment therefore also covers paths no
    agent supplied: the manifest walk and links read out of a concept. `LocalDocumentStore` enforces it
    during **traversal** as well as access — `..` segments and absolute paths are rejected, and a
    symlink resolving outside `root` is skipped by the walk and refused on read.
  - `list()` returns paths in **lexicographic order**. Ordering is part of the contract because
    `max_concepts` truncation keeps a prefix of the walk: an unordered store would give two pods
    different concept sets for the same over-limit bundle.
- `LocalDocumentStore(root: str)` — local filesystem. No extra required (stdlib only).
- `S3DocumentStore(bucket: str, prefix: str = "", region: str | None = None, client=None)` — requires
  the existing `aws` extra (`boto3>=1.41.4`, already in `pyproject.toml`); no new extra.
  - `list()` paginates and merges pages in key order (S3 already lists in UTF-8 binary order);
    `read_bytes` maps `NoSuchKey` to `FileNotFoundError` so the layer above sees one exception type
    regardless of store.
- `DocumentStore.from_uri(uri)` resolves by **explicit scheme**: `file://…` or a bare path →
  `LocalDocumentStore`; `s3://bucket/prefix` → `S3DocumentStore`; `python:pkg.module.ClassName` →
  `resolve_dotted` (`core/util/factory.py:26`). Any other scheme raises `AKConfigError`.
  - The `python:` prefix is required because a dotted path *is* a bare path. Without a discriminator,
    `mypkg.stores.GitStore` would silently become a `LocalDocumentStore` rooted at a directory that
    does not exist, and the bring-your-own-store branch would be unreachable.
  - This is what makes local-in-dev / S3-in-prod a one-environment-variable change without the KB
    tier gaining an `AKConfig` section (see [Decisions](#decisions) 1).
- Stores take **explicit constructor parameters and never read `AKConfig`**, matching the shared-driver
  and transport rules.

### Representation layer — OKF parsing

- New `knowledgebase/okf/` package holding the format only. It takes `bytes`/`str` in and returns
  objects; it never touches a `DocumentStore` or a network.
- `OKFConcept`: the parsed document — `path` (its identity), `type` (the only required frontmatter
  field), and the identity / provenance / trust / lifecycle / computation families, plus the markdown
  body and its outbound links.
- `OKFBundle`: the parsed tree — concepts keyed by path, reserved files (`index.md`, `log.md`), the
  declared `okf_version` from the bundle-root `index.md` frontmatter, and a **diagnostics list**.
- YAML frontmatter is parsed with `pyyaml`, already a **core** dependency
  (`ak-py/pyproject.toml`), so a local-filesystem OKF backend needs **no optional extra at all**.
- **Tolerant by specification** — the research is explicit that a strict OKF reader is a
  non-conformant one (`research/okf-format-survey.md` §5). Concretely:
  - A file that fails to parse, or lacks a non-empty `type`, is **skipped with a diagnostic**; the
    bundle still loads.
  - Unknown frontmatter keys, unknown `type` values, missing optional fields, a missing `index.md`,
    and broken links are all carried through, never rejected.
  - A bare `verified` mapping is normalised to a one-element list.
  - **v0.2 only** (see [Decisions](#decisions) 5). No v0.1 translation: a v0.1 `timestamp` key or a
    body `# Citations` list is carried through as an unknown key / ordinary body text, never mapped
    onto `generated` / `sources`. A bundle declaring any other `okf_version` still loads; the
    mismatch is recorded as a diagnostic, never a rejection.
  - Diagnostics are **surfaced**, not swallowed: exposed on the bundle, logged at `warning` on load,
    and reported through `get_description()`.
- Trust tier is derived only from `verified` — absent → `unverified`; present with no `human:` actor →
  `machine-confirmed`; present with a `human:` actor → `human-reviewed`. Staleness is derived only
  from `stale_after`. Both are **advisory signals attached to every returned record**; nothing is
  ever filtered out on their basis, and that must be asserted by a test.
- Links are extracted in both specified forms — bundle-absolute (`/tables/x.md`) and relative
  (`./x.md`) — resolved to bundle-relative paths and attached as `metadata["links"]`, so an agent can
  traverse the graph with `fetch`.

### `DocumentKnowledgeBase` and `OKFManager`

- `DocumentKnowledgeBase` (abstract, `knowledgebase/document.py`) is the **only** new intermediate
  base class, and it exists because it carries real shared behavior for any path-addressed
  collection: holding the `DocumentStore`, mapping a store's containment refusal to an agent-facing
  error result and `FileNotFoundError` to an empty one, and folding `store.writable` into its
  capabilities. Containment itself is enforced by the store, not here.
- `OKFManager(store, name="", description=None, refresh_seconds=300, max_concepts=10_000)` composes
  the store with the OKF parser, and builds its capabilities **in `__init__`** from what it was given:
  `kinds=["document"], search=True, search_mode="lexical", query=False, fetch=True, browse=True,
  writable=store.writable, derives_schema=True`.
  - `writable` is the reason capabilities are per instance — the same class over a read-only
    `S3DocumentStore` prefix declares `writable=False`.
  - `query=False` (and so `query_language=None`) means `read()` routes to `search()` under the rule
    in [Operation set](#operation-set-on-knowledgebase), and `search_kb` is not emitted on its
    account.
  - `fetch(ids)` — bundle paths in, concept records out. The natural companion to `metadata["links"]`.
  - `browse(path)` — directory listing. At **any** level, an `index.md` in the browsed directory
    supplies the listing when present, and a derived listing is returned when it is not. `index.md` is
    reserved at every directory level (`research/okf-format-survey.md` §2), so a curated listing for
    `datasets/` is honoured exactly as the bundle root's is.
  - `search(query, limit)` — **lexical**, over frontmatter (`title`, `description`, `tags`, `type`)
    and body text, ranked by field-weighted term overlap. Declared as `lexical` precisely so no
    caller mistakes it for embedding search.
  - `write(records)` — emits **conformant** concept documents: a non-empty `type`, and
    `generated: {by, at}` stamped with the writing actor in the `<producer>/<version>` convention.
    Kept because producing OKF is the format's intended agent workflow, not only consuming it
    (`research/okf-format-survey.md` §8).
    - **Writing actor**: `agentkernel/<installed agentkernel version>` by default, overridable per
      manager for an application that wants to be named as the producer. One string, resolved once at
      construction rather than per write; `spec.md` fixes its exact form.
    - **Write-through to the manifest**: a successful `write()` inserts or replaces that concept's
      manifest entry in the same call, so the written concept is visible to `fetch`, `browse`, and
      `search` **immediately** — never after up to `refresh_seconds`. An agent that writes a concept
      and then cannot read it back for five minutes would be a surprising tool surface. Asserted by a
      test running with `refresh_seconds=None`, which proves the visibility comes from the write
      itself and not from a refresh happening to fire.
    - **Ids stay comma-free**: `write()` refuses a bundle path containing a `,`, which is what keeps
      every id it hands out round-trippable through `fetch_kb` — see [Agent
      surface](#agent-surface--knowledgebuilder).
  - `format_results` renders `id`, `title`, `type`, trust tier, and a staleness marker, so routing
    information reaches the agent rather than being flattened away.
- **Bundle manifest and cost.** `connect()` walks the store once and holds a parsed manifest in
  process.
  - Without it, one `browse` or `search` over an S3 bundle is one `list` plus one `get` per object,
    on every agent tool call.
  - `refresh_seconds` **defaults to 300**: the manifest re-walks lazily on the first access after the
    interval has elapsed, so a bundle rewritten by a separate producer pipeline is picked up without a
    restart. `reload()` forces an immediate re-walk; `refresh_seconds=None` disables automatic
    refresh for a bundle known to be immutable.
  - **Concurrency**: the lazy re-walk is guarded, so two tool calls crossing the boundary together
    produce **one** walk, not two. The first caller takes the lock and re-walks; a concurrent caller
    does not block on it and is served the current manifest, one interval stale. The new manifest is
    swapped in as a whole, so no caller ever observes a half-built one.
  - Stated consequence: an **external** edit made underneath a running process is seen at most
    `refresh_seconds` later, and the re-walk cost lands on whichever agent tool call crosses the
    boundary. This is the deliberate trade and must be documented on the backend. It does not apply to
    the manager's own `write()`, which is write-through (above).
  - Bodies of large bundles are read lazily per concept; frontmatter is parsed eagerly, because
    schema derivation and search ranking both need it.
- **Declared scale.** The manifest is held per *process*, so its cost is paid once per pod in the
  ECS/pipeline topology and once per cold start on Lambda. The design targets a stated envelope
  rather than leaving it open:
  - **Design target: bundles up to 10,000 concepts**, at which the manifest is expected to stay
    under 250 MB — ~19 KB per concept measured, 25 KB budgeted. Both numbers are asserted by a test
    over a generated bundle, so a regression in per-concept overhead is caught rather than discovered
    in a pod.
    - The original ~50 MB figure was corrected during implementation: 45 MB is the floor for 10,000
      parsed concepts with *no* body index at all, and the index itself was bounded in bytes read
      rather than tokens retained, which put a bundle of ordinary prose at 770 MB. `spec.md`'s
      Manifest section carries the measurements and the `BODY_INDEX_MAX_TOKENS` cap that fixed it.
    - The memory assertion is measured with `tracemalloc` around the manifest build — allocations
      attributable to the manifest — **not** process RSS, which moves with the interpreter, the
      allocator's retained arenas, and whatever else the test session has loaded. RSS is not
      deterministic enough to gate CI on.
  - `max_concepts` **defaults to 10,000**: the walk stops at the limit, keeps the concepts it has, and
    records a diagnostic naming the count and the limit. It is a bound on memory, not a conformance
    rule — the bundle still loads and serves, consistent with the tolerance requirement above.
  - Bodies are excluded from the envelope: they are read on demand and not retained between calls, so
    total bundle *bytes* on disk or in S3 is not the limiting dimension — concept count is.
  - A deployment needing more raises `max_concepts` explicitly and owns the memory consequence. There
    is no automatic spill to disk, no LRU eviction, and no shared cross-pod cache; each is a
    non-goal below.

### Agent surface — `KnowledgeBuilder`

- The four existing tools keep their names and signatures: `get_schemas`, `read_kb`, `write_kb`,
  `get_all_kb_descriptions`.
- Three new capability-gated tools:
  - `search_kb(backend: str, query: str, limit: int = 3) -> str` — relevance retrieval, calling
    `search()` directly.
  - `fetch_kb(backend: str, ids: str) -> str` — comma-separated ids, split on `,` and stripped, with
    empty segments dropped. Kept a flat string rather than a JSON-array string because tool arguments
    are flat strings and a JSON argument is a parse failure agents hit routinely.
    - **The separator constrains the id space**, and for OKF that constraint is real rather than
      theoretical: the id is a bundle path, and a `,` is legal in a POSIX filename. So it is enforced
      at both ends — `OKFManager.write()` refuses a path containing a `,`, and the manifest walk skips
      such a file with a diagnostic — which keeps every id the backend hands out round-trippable.
    - Generalised to the contract: a backend whose ids cannot be comma-free must not declare `fetch`.
      Asserted by `KnowledgeBaseContract`.
  - `browse_kb(backend: str, path: str = "", limit: int = 50) -> str`.
  - Each is included in `build()`'s output **only when at least one registered backend declares that
    capability**, so a vector-only application's tool list is unchanged.
  - Routing a call at a backend that does not declare the capability returns an actionable string
    naming the backends that do — matching `read_kb`'s existing error-to-string behavior
    (`knowledgebuilder.py:118-119,128-130`), never an exception into the framework.
- **Why `search_kb` exists**: without it, a backend declaring both `search` and `query` has an
  unreachable `search()`, because `read()` routes to `query()` whenever `capabilities.query` is
  `True`.
  - No in-tree backend is affected today — Chroma is search-only, Neo4j and Starburst are query-only,
    OKF is search-only — but the capability model exists precisely so backends can grow, and a
    declared-but-unreachable capability would be the same dishonesty the model is meant to remove.
  - `search_kb`'s gate is narrower than the other two: it is emitted only when at least one backend
    declares **both** `search` and `query`. For a search-only backend `read_kb` already reaches
    `search()`, and emitting a second tool that does the same thing would only give the agent a
    redundant choice.
  - The gate is a property of the registered set, not of one backend: once emitted, `search_kb` routes
    at any backend declaring `search`, and returns the capability string for the others.
- `write_kb` stops emitting Neo4j's `cypher_query` / `cypher_params` keys
  (`knowledgebuilder.py:156-167`); it emits the generic `query` / `params` only.
  - **`Neo4jManager.write` changes in the same commit.** It reads *only* the `cypher_*` spelling today
    (`neo4j.py:120-121`), so dropping those keys without touching it would call `_run(None, {})` on
    every agent-issued write. It is changed to read `query`/`params` first and fall back to
    `cypher_query`/`cypher_params`, keeping hand-written old-shape records working, and to skip a
    record carrying neither with a logged warning rather than handing `None` to the driver.
- `get_schemas` gains the same per-backend `try/except` its sibling `get_all_kb_descriptions` already
  has (`knowledgebuilder.py:185-187`), reporting the failing backend inline instead of failing the
  whole call.
- Semantic-map placeholder resolution (`knowledgebuilder.py:76-89`) applies to `fetch_kb` ids and
  `browse_kb` paths as well as queries, so an OKF bundle root can be an environment-swappable token.

### Extensibility

- Adding a KB type requires: subclass `KnowledgeBase` (or `DocumentKnowledgeBase`), declare
  `KnowledgeCapabilities`, override the operations declared. No change to `KnowledgeBuilder`, the
  tools, or any framework adapter.
- Adding a **storage** backend for an existing representation requires only a `DocumentStore`
  subclass — an HTTP-served or git-backed OKF bundle is a store, not a new KB.
- `knowledgebase/testing.py` ships `KnowledgeBaseContract` and `DocumentStoreContract`, reusable
  suites in the `SandboxProviderContract` (`sandbox/testing.py:130`) / `QueueTransportContract` shape.
  `KnowledgeBaseContract` asserts, for any backend: declared capabilities match implemented
  operations; undeclared operations raise `KnowledgeCapabilityError`; `schema()` is callable and
  returns a mapping (the `StarburstManager` collision above); records carry `metadata["id"]` when
  `fetch` is declared, and that id contains no `,`; unknown keys round-trip at both record and
  metadata level; every operation accepts `**kwargs`; both construction-time invariants are enforced
  and each error names the backend without reading `backend_name`; and `read()` routes on
  `capabilities.query` — to `query()` when it is `True`, to `search()` otherwise.
- `knowledgebase/__init__.py` gains **lazy** exports via PEP 562 `__getattr__` (the
  `deployment/aws/__init__.py` pattern) for `KnowledgeBase`, `KnowledgeBuilder`,
  `KnowledgeCapabilities`, `Record`, `KnowledgeRecord`, `KnowledgeMetadata`, and the errors — fixing
  the import documented at `docs/docs/core-concepts/overview.md:353` without making
  `chromadb`/`neo4j`/`trino`/`boto3` eager.

### Example and documentation

Steps 7-8 of `ak-dev-new-knowledgebase-integration` make a runnable example and the docs surfaces part
of "complete" for a new backend, and the PR guidelines ask for an example with a new feature. Both are
**requirements of this change**, not a later docs-sync iteration:

- `examples/cli/knowledgebase/openai/okf/` — in the shape of its siblings (`chromadb/`, `neo4j/`,
  `starburst/`): a small checked-in OKF bundle served by a `LocalDocumentStore`, an agent wired
  through `KnowledgeBuilder`, and a `README.md` exercising `browse_kb` → `fetch_kb` → `search_kb`
  against real bundle paths, which is the capability-gated tool set this change exists to make
  reachable.
- `docs/docs/advanced/knowledge-bases.md` — the capability model (`KnowledgeCapabilities`, the five
  operations, which tools each capability emits), the OKF backend, and `DocumentStore` local-vs-S3
  configuration.
- `docs/docs/core-concepts/overview.md` — the documented import at `overview.md:353` starts working
  with the lazy exports above; the surrounding text is corrected from `read`/`write` alone to the
  operation set.
- The prompt-visible migration items — `schema()` gaining `"capabilities"`, and `StarburstManager`'s
  `schema` attribute becoming `db_schema` — are called out in the docs, because they change what an
  already-deployed agent sees.

### Security

- **Path containment is the `DocumentStore`'s obligation**, stated in the store contract above rather
  than left to each caller — so it covers paths that reach a store from anywhere: an agent
  (`fetch`/`browse`/`write`), a link read out of a concept, and the manifest walk, which supplies no
  agent path at all. `..` segments, absolute paths, and symlinks resolving outside
  `LocalDocumentStore.root` are refused on access and skipped during traversal.
  `DocumentKnowledgeBase` turns the refusal into an error result for the agent; it never stands in as
  the only place an escape is detected.
- **No network fetch of OKF reference fields**: `resource`, `sources[].resource`, and `computation`
  values that are absolute URLs are returned to the agent as data and never dereferenced by the KB
  layer, matching the multimodal hook's stance on remote references
  (`core/multimodal/hooks.py:41,344`).
- Concept body text is untrusted content authored by whoever produced the bundle. It is returned as
  data; nothing in the KB layer acts on instructions found inside a concept.

### Error handling

- Missing/unreadable document → empty result plus a logged warning; never a traversal or a raise into
  the framework.
- Malformed concept → skipped with a diagnostic; the bundle still loads (specification requirement).
- Missing store configuration (no bucket, unreadable root) → `ValueError` at construction, matching
  `StarburstManager.connect`'s missing-config behavior (`starburst.py:102`).
- Missing `boto3` for `s3://` → `ImportError` naming the `aws` extra, via `require_extra`
  (`core/util/factory.py:50`).
- Unresolvable `from_uri` value → `AKConfigError`.
- Undeclared operation → `KnowledgeCapabilityError`, caught at the tool boundary and returned as an
  actionable string.

## Migration and behavioural changes

Each is intentional; each needs a test.

1. `KnowledgeBase.read` becomes concrete, delegating to `query()`/`search()`. Existing overrides in
   `ChromaManager`, `Neo4jManager`, `StarburstManager` are **renamed** to `search`/`query`/`query`
   respectively; the base alias preserves `read()` for every caller. A third-party subclass that
   overrides `read()` is unaffected.
2. `StarburstManager.write` raises `KnowledgeCapabilityError` instead of `NotImplementedError`
   (`starburst.py:141`). `KnowledgeCapabilityError` does **not** subclass `NotImplementedError`, so
   any caller catching the old type must be updated — in-tree there are none.
3. `schema()` no longer raises when `add_schema()` was skipped **and** the backend derives its own
   (`base.py:57-58`). For the three existing backends, all of which declare
   `derives_schema=False`, behavior is unchanged.
4. `schema()` output gains `"capabilities"`. This changes the JSON `get_schemas` returns to the
   agent — additive, but it is a prompt-visible change.
5. `write_kb` no longer writes `cypher_query`/`cypher_params` into record metadata
   (`knowledgebuilder.py:157-166`). Neo4j reads the generic keys with the old keys as fallback, so
   agent-issued writes are unaffected; **records already stored by Chroma carry the dead keys and are
   not migrated**.
6. `get_schemas` degrades per backend instead of failing the call.
7. `build()` may return up to seven callables rather than four, when registered backends declare
   `fetch`, `browse`, or both `search` and `query`.
8. `agentkernel.knowledgebase` exports names for the first time — additive; the documented import
   starts working.
9. `StarburstManager`'s Trino schema name moves from `self.schema` to `self.db_schema`
   (`starburst.py:67`). The `schema=` constructor keyword is unchanged, so no call site moves; code
   reading `manager.schema` as a string must be updated — in-tree there is none, and the read now
   returns the inherited `schema()` method. `get_schemas` starts returning a real schema for
   Starburst backends instead of raising `TypeError`, which is a prompt-visible change for every
   Starburst deployment.
10. `format_results` prefixes `[<id>]` for backends declaring `fetch`. No existing backend declares
    it, so in-tree output is unchanged; the rule is listed because it is prompt-visible the moment a
    `fetch`-capable backend is registered.
11. `Neo4jManager.query` (formerly `read`) defaults to `limit=3` instead of `limit=10`
    (`neo4j.py:125`). `read_kb` always passes `limit`, so only direct callers see it.
12. `Neo4jManager.write` reads the generic `query`/`params` metadata keys, falling back to
    `cypher_query`/`cypher_params`, and skips a record carrying neither with a logged warning instead
    of calling the driver with `None` (`neo4j.py:118-123`). Required by item 5: `write_kb` no longer
    emits the `cypher_*` keys, and the fallback is what keeps old-shape records working.
13. `KnowledgeBase.__init__` requires a `capabilities` argument (`name` stays optional). A
    third-party subclass calling `super().__init__()` with no arguments must pass one — the only
    signature in this change that is not backward compatible, and the reason capability declaration is
    not optional. Every functioning bring-your-own backend calls `super().__init__()` today, since
    that is what initializes `_dynamic_schema` (`base.py:29`), so this item reaches all of them; the
    "no edit needed" claim under [Operation set](#operation-set-on-knowledgebase) is about the `read()`
    path only.

**Non-changes**, to be asserted: `Record` stays `Mapping[str, Any]` and stays the type on every
signature (`KnowledgeMetadata`/`KnowledgeRecord` are documentation-only); `read`/`write` signatures,
including their `**kwargs`, which every new operation also carries; the four existing tool names and
signatures; `KnowledgeBuilder.__init__`'s `backends` + `semantic_map` signature;
`add_schema`/`format_results`/`close`; the `schema=` keyword on `StarburstManager.__init__`; no
framework adapter changes; no `AKConfig` section added; every existing example
(`examples/cli/knowledgebase/openai/*`) runs unmodified.

## Deviations from the proposed class diagram

The input diagram's storage half — `OKFManager o-- OKFStorage`, `LocalOKFStorage` / `S3OKFStorage` —
is adopted as-is in substance. Two changes:

- **`VectorKB` / `StructuredKB` / `FileSystemKB` become `capabilities.kinds`, not base classes.**
  - The diagram has `Neo4jManager` inheriting from both `VectorKB` and `StructuredKB`. That is a
    diamond whose only purpose is to say "this backend is two things" — which a declared list says
    directly, and which today's `Neo4jManager` does not even need, since it is Cypher-only
    (`neo4j.py:125-146`) with no vector index.
  - `AGENTS.md` forbids exactly this: *"Don't invent a new intermediate abstraction 'for consistency'
    across adapters… forcing uniformity across adapters is itself an opinion the architecture
    avoids."* (`AGENTS.md:67-69`) Marker classes carrying no behavior are that abstraction.
  - The repo has already answered "what can this backend do?" with declared data rather than type
    identity, in `SandboxCapabilities` (`sandbox/model.py:33-48`).
  - The taxonomy is not lost — it becomes stronger, because `kinds` reaches the agent through
    `get_schemas()` where an inheritance edge never could.
  - `DocumentKnowledgeBase` **is** kept as a base class, because unlike the other three it carries
    real shared implementation (store composition, path containment, error mapping) that a second
    document-shaped KB would otherwise duplicate.
- **`OKFStorage` → `DocumentStore`.** The store reads bytes at paths; it has no OKF knowledge, and
  naming it for one format would make it look wrong to reuse for the next path-addressed
  representation. `OKFManager` keeps the `*Manager` suffix of its siblings for discoverability.

## Non-goals

- **Executing Attested Computations.** `type: Attested Computation` concepts are read like any other
  concept; the executor/attester workflow runs arbitrary code and belongs to the sandbox capability
  (`research/okf-format-survey.md` §7).
- **Embedding an OKF bundle into a vector store.** Semantic search over a bundle is achieved by
  composing an OKF backend with a vector backend in one `KnowledgeBuilder` — not by giving
  `OKFManager` an embedder.
- **An OKF authoring/enrichment agent.** `write` emits conformant documents; the producer-side
  pipeline is a separate change.
- **A `knowledgebase` block in `AKConfig`.** Backends stay application-constructed, as today.
- Bundle-level concurrency control, versioning, or locking on write.
- A shared or cross-pod manifest cache, spill-to-disk, or LRU eviction. The manifest is per process
  and bounded by `max_concepts`; a bundle outgrowing that envelope is a separate change.
- Changing any framework adapter, `Runtime`, `Session`, or the system-tool factory. Knowledge-base
  tools remain application-bound through `KnowledgeBuilder.build()`.
- Migrating metadata already written by the current `write_kb` (item 5 above).
- Rewriting `semantic_map`, the KB router pattern, or the **existing** examples. The new OKF example
  and the docs updates are in scope — see [Example and documentation](#example-and-documentation).

## Decisions

Resolved with the maintainer on 2026-08-31. The requirements above already reflect them.

1. **Config — no `AKConfig` section.** Applications construct the backend and its `DocumentStore`
   explicitly, as they do today. `DocumentStore.from_uri` keeps local-in-dev / S3-in-prod a one-string
   change; reading that string from the environment stays the application's job.
2. **`kinds` — open `list[str]`.** `vector`, `structured`, `graph`, `document` are documented
   conventional values, not a closed enum. Extensibility wins over agent-side routability, and the
   values are advisory anyway — routing is driven by the boolean capability flags and
   `get_description()`, not by `kinds`.
3. **Record typing — `KnowledgeMetadata` + `KnowledgeRecord` as `TypedDict`s.** Two types, because
   the reserved keys live inside `metadata` while the record itself is `{"text", "metadata"}`; one
   type covering both levels would leave "a `fetch`-capable backend must set `id`" ambiguous about
   where `id` goes. `Record` stays `Mapping[str, Any]` on every signature, so no existing backend or
   user subclass is invalidated, and the `id` rule is enforced by `KnowledgeBaseContract` rather than
   by runtime validation.
4. **Manifest refresh — lazy automatic refresh, `refresh_seconds` default 300.** The manifest re-walks
   on the first access after the interval elapses; `reload()` forces one immediately;
   `refresh_seconds=None` opts out for an immutable bundle. Chosen so an S3 bundle rewritten by a
   separate producer pipeline is picked up without a restart. It governs external producers only —
   the manager's own writes are write-through (item 10).
5. **OKF version — v0.2 only.** No v0.1 read translation and no v0.1 writes. A v0.1 bundle still
   *loads*, because the conformance rules forbid rejecting a concept for unknown frontmatter keys —
   but `timestamp` and a body `# Citations` list are carried through as unrecognised content rather
   than mapped onto `generated` / `sources`, and a declared `okf_version` other than `0.2` is recorded
   as a bundle diagnostic.
6. **Capabilities are per instance, not per class.** `Sandbox` fixes its shape on the class
   (`sandbox/base.py:88`); a KB's shape depends on its constructor arguments — `writable` follows the
   injected `DocumentStore`. Validated in `KnowledgeBase.__init__`, which is what makes the
   at-least-one-capability invariant enforceable.
7. **Manifest envelope — 10,000 concepts / 250 MB (~19 KB per concept measured; the ~50 MB first
   stated was corrected against measurement), `max_concepts` truncates with a diagnostic.** A
   declared and tested bound, rather than an open-ended in-process cache, because the manifest is
   held per pod and per Lambda cold start. Raising it is an explicit, application-owned decision.
8. **Verification gate — stands.** Every `[SPEC]`-marked claim in `research/okf-format-survey.md` must
   be re-checked verbatim against the OKF **v0.2** specification text before `spec.md` fixes
   conformance behavior.

Items 9-11 were resolved in review of this document on 2026-09-01.

9. **`read()` routes on `capabilities.query`, and `query_language` is bidirectional with it.** Gating
   on `query_language` left `query=False` with a language set constructible, which would have routed
   `read()` at a `query()` that raises even though `search` was declared and implemented. The boolean
   is the gate, the invariant makes the two inseparable, and the rule is stated once — in [Operation
   set](#operation-set-on-knowledgebase).
10. **`write()` is write-through, not refresh-delayed.** A concept is visible to `fetch`/`browse`/
    `search` in the call after the write, independent of `refresh_seconds`. `refresh_seconds` governs
    *external* producers only. The alternative — the manager's own writes invisible for up to five
    minutes — is a tool surface no agent could reason about.
11. **`fetch_kb` ids stay comma-separated, and ids are constrained to match.** A JSON-array argument
    trades a parse failure agents hit routinely for an id-space restriction they never hit; the
    restriction is enforced at write and walk time rather than assumed, so it cannot silently produce
    an unfetchable id.
