---
sidebar_position: 5
---

# Knowledge Bases

Agent Kernel provides a **backend-agnostic knowledge base interface** that lets agents retrieve and persist long-term knowledge across storage systems - vector stores, graph databases, SQL engines, and directories of markdown documents - through one consistent API. Each backend **declares what it supports** in a `KnowledgeCapabilities` object, and both the interface and the agent's tool set follow that declaration: an operation a backend does not declare is never offered to the agent.

This builds on top of core session and memory concepts:
- **Session + caches** → short‑ and medium‑term conversation state.
- **Knowledge bases** → durable, cross‑session knowledge.

## Core Abstractions

### `KnowledgeBase`

`KnowledgeBase` is an abstract interface implemented by concrete backends:

- `ChromaManager`: ChromaDB vector store for semantic text recall.
- `Neo4jManager`: Neo4j graph database for entities and relationships.
- `StarburstManager`: Starburst Galaxy (read-only SQL via Trino) for querying structured data in MongoDB, Google Sheets, PostgreSQL, and other Trino-connected sources.
- `OKFManager`: an [Open Knowledge Format](https://openknowledgeformat.org) bundle - a directory of markdown documents with YAML frontmatter - served from a local directory or an S3 prefix, with no database and no service to run. See [`DocumentStore` and the OKF backend](#documentstore-and-the-okf-backend).

For Starburst operational details, see Starburst Galaxy documentation:
- https://docs.starburst.io/starburst-galaxy/

**Three members are abstract.** Every backend implements exactly these:

- `backend_name: str`: unique identifier (used by tools and schemas).
- `connect(**kwargs) -> None`: establish any underlying client connections.
- `get_description() -> str`: human-readable description for routing decisions.

**Everything else is optional, and the capability declaration decides which ones apply.** An operation a
backend does not declare raises `KnowledgeCapabilityError` rather than returning an empty result, so the
declaration and the implemented set must agree:

| Declare | Implement | Purpose |
|---|---|---|
| `search` | `search(query, limit=3)` | relevance retrieval |
| `query` + `query_language` | `query(statement, limit=3)` | query-language retrieval (Cypher, SQL, ...) |
| `fetch` | `fetch(ids)` | retrieval by identity |
| `browse` | `browse(path="", limit=50)` | namespace enumeration |
| `writable` | `write(records)` | persistence |

`read(query, limit=3)` is **concrete and must not be overridden**. It routes on the declaration - to
`query()` for a backend declaring `query`, to `search()` for every other backend - which is what lets one
`read_kb` tool serve every backend.

The base also provides `add_schema()`, `schema()`, `_derived_schema()`, `format_results()` and `close()`;
see [Schemas](#schemas) and [Optional overrides](#optional-overrides).

Records are plain mappings of the shape `{"text": ..., "metadata": {...}}`. `Record` is `Mapping[str, Any]`
on every signature; `KnowledgeRecord` and `KnowledgeMetadata` are `TypedDict`s that document the
conventional metadata keys (`id`, `source`, `title`, `kind`, `trust`, `stale`, `links`) and are never
validated at runtime.

The core names import from the package root:

```python
from agentkernel.knowledgebase import (
    KnowledgeBase,
    KnowledgeBuilder,
    KnowledgeCapabilities,
    Record,
    DocumentStore,
    LocalDocumentStore,
    OKFManager,
)
```

Names resolve lazily, so importing the package costs one module import and pulls no optional SDK.
`S3DocumentStore` is exported the same way, but it is the one name whose resolution has a cost: touching
it imports `boto3`, so it needs the `aws` extra installed.

```python
from agentkernel.knowledgebase import S3DocumentStore  # requires agentkernel[aws]
```

The three SDK-backed managers are deliberately **not** exported from the package root: each imports its
client library at module import, so exporting them would make `chromadb` / `neo4j` / `trino` a hard
requirement for anyone importing the package. Import those from their own modules:

```python
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.knowledgebase.starburst import StarburstManager
```

### `KnowledgeCapabilities`

What a backend declares to `super().__init__()`:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `kinds` | `list[str]` | `[]` | open taxonomy - `vector`, `structured`, `graph`, `document`, ... |
| `search` | `bool` | `False` | implements `search()` |
| `search_mode` | `"semantic"` \| `"lexical"` \| `None` | `None` | advisory only; does not imply `search` |
| `query` | `bool` | `False` | implements `query()` |
| `query_language` | `str` \| `None` | `None` | for example `"cypher"`, `"sql"` |
| `fetch` | `bool` | `False` | implements `fetch()` |
| `browse` | `bool` | `False` | implements `browse()` |
| `writable` | `bool` | `False` | implements `write()` |
| `derives_schema` | `bool` | `False` | `schema()` self-describes without `add_schema()` |

`KnowledgeBase.__init__` enforces two invariants and raises `ValueError` naming the backend otherwise:

- At least one of `search` / `query` / `fetch` / `browse` / `writable` must be `True`.
- `query=True` requires a `query_language`, and a `query_language` requires `query=True`.

`KnowledgeBase.validate_capabilities(capabilities, subject)` is a static method, so a declaration can be
checked without constructing a backend.

What each built-in backend declares:

| Backend | `kinds` | Declares |
|---|---|---|
| `ChromaManager` | `vector` | `search` (`semantic`), `writable` |
| `Neo4jManager` | `graph`, `structured` | `query` (`cypher`), `writable` |
| `StarburstManager` | `structured` | `query` (`sql`); **not** writable |
| `OKFManager` | `document` | `search` (`lexical`), `fetch`, `browse`, `writable`*, `derives_schema` |

\* folded with the document store's own writability - see below.

### Schemas

`schema()` is what `get_schemas()` returns to the agent. It merges, in order: `{"backend": backend_name}`,
whatever `_derived_schema()` produced, whatever `add_schema()` was given, and finally `"capabilities"` -
written last and therefore **not overridable**, because it is the declaration the tool layer routes on.

A backend that neither received an `add_schema()` call nor derives its own schema raises `ValueError`.
Declare `derives_schema=True` and override `_derived_schema()` to self-describe instead; `OKFManager` does
exactly that and needs no `add_schema()` call at all.

### Errors

Every knowledge-base failure subclasses `KnowledgeError`. Finding nothing is **not** a failure - a read
that matches no records returns an empty list, and a malformed document is skipped with a diagnostic.

- `KnowledgeCapabilityError`: an operation the backend does not declare. Deliberately **not** a
  `NotImplementedError`, so it stays distinguishable from an unimplemented abstract method. `KnowledgeBuilder`
  catches it at the tool boundary and returns an actionable string to the agent.
- `KnowledgePathError`: a path escaped a `DocumentStore` namespace, or is otherwise unusable as an identity.

### `DocumentStore` and the OKF backend

Document-shaped knowledge splits into two independent axes:

- **Storage** - a `DocumentStore` supplies bytes at paths. `LocalDocumentStore` reads a directory;
  `S3DocumentStore` reads a bucket prefix.
- **Representation** - a `DocumentKnowledgeBase` subclass decides what those bytes mean. `OKFManager` reads
  them as Open Knowledge Format concepts.

Because the axes are independent, moving a bundle from a laptop to an object store is a store swap, not a
backend change.

#### Configuring a store

```python
from agentkernel.knowledgebase import DocumentStore, LocalDocumentStore, OKFManager

# Explicit: a directory checked into the repository, served read-only.
kb = OKFManager(LocalDocumentStore("./bundle", writable=False), name="OKF")

# Or resolved from one configuration string, so the same code serves both environments.
kb = OKFManager(DocumentStore.from_uri("s3://my-bucket/bundles/warehouse"), name="OKF")
```

`DocumentStore.from_uri()` accepts four forms:

| Value | Resolves to |
|---|---|
| `./bundle`, `/srv/kb` | `LocalDocumentStore` |
| `file:///srv/kb` | `LocalDocumentStore` |
| `s3://bucket/prefix` | `S3DocumentStore` (needs the `aws` extra) |
| `python:mypkg.stores.GitStore` | your own `DocumentStore` subclass |

The `python:` discriminator is mandatory rather than inferred: a dotted path is itself a valid filesystem
path, so without it `mypkg.stores.GitStore` would silently become a local store rooted at a directory that
does not exist. Any other scheme raises `AKConfigError`.

Writability is asymmetric by design. `LocalDocumentStore(root, writable=None)` probes the filesystem, while
`S3DocumentStore(..., writable=True)` is a declaration and defaults to writable, because probing a bucket
would mean writing to it. The store's writability then folds into the backend's declaration with `and`, so
the more restrictive side always wins: a read-only store beats a backend willing to write, and a backend
that chooses not to write beats a writable store.

**Path containment is the store's obligation, not the caller's.** `..` segments, absolute paths, and symlinks
resolving outside a local root are refused on access and skipped during traversal - wherever the path came
from, whether an agent tool, a link inside a document, or the manifest walk.

#### The OKF backend

```python
OKFManager(
    store,
    name="",
    description=None,
    refresh_seconds=300.0,   # None disables automatic refresh entirely
    max_concepts=10_000,
    producer=None,           # stamped into generated.by on write
    write_prefix="generated",
)
```

An OKF bundle is a directory of markdown documents, each carrying YAML frontmatter, targeting OKF version
`0.2`. `index.md` and `log.md` are reserved at **every** level, not only the root: a directory holding an
`index.md` is browsed by returning that file verbatim - a listing a human wrote beats one derived from the
filesystem - and `log.md` is never a concept.

Because a bundle already states its own version, types and layout, `OKFManager` declares
`derives_schema=True` and answers `get_schemas()` from the bundle itself: the version, the concept count,
the types in use, the top-level namespaces, the reserved files, how many diagnostics the walk produced, and
whether it was truncated at `max_concepts`.

**Tolerance is a specification requirement.** A document that cannot be parsed is skipped with a diagnostic
and the bundle still loads; the diagnostics are surfaced through `get_all_kb_descriptions()` rather than
swallowed. Every record carries `metadata["trust"]` (`unverified`, `machine-confirmed` or `human-reviewed`,
derived from the document's `verified` block) and `metadata["stale"]` (derived from `stale_after`), and
**nothing is ever filtered on either** - the format makes them advisory signals, not grounds for rejection.

Only `fetch` reads a full document body. `search` and `browse` answer from an in-process manifest holding
frontmatter plus a bounded token index, which is what keeps a large bundle affordable - so a concept's
complete text and its `links` become available only after a fetch.

**The refresh cost, stated plainly.** `connect()` walks the whole store once and is called from `__init__`,
so constructing a manager blocks until that walk finishes - deliberate, so a misconfigured store fails at
construction rather than inside an agent's first tool call. Thereafter every operation is one clock
comparison, except the call that crosses the `refresh_seconds` boundary, which pays a fresh walk: for a
local bundle one directory walk plus one bounded read per document; for S3 one paginated listing plus **one
ranged GET per concept, per refresh, per pod**. At the 10,000-concept design target and the 300-second
default, that is 10,000 ranged GETs every five minutes in every pod. Raise `refresh_seconds` for a large S3
bundle, or set it to `None` for one known to be immutable and call `reload()` when it changes.

Writes are write-through. A written concept lands under `write_prefix` (`generated/` by default) as an
ordinary OKF document stamped with a `generated:` block naming the producer, and is visible to `browse`,
`fetch` and `read` on the very next call, because the write updates the manifest directly rather than
waiting for a refresh.

A runnable end-to-end example, with a checked-in bundle, lives at
`examples/cli/knowledgebase/openai/okf/`.

## KnowledgeBuilder and Tools

`KnowledgeBuilder` composes one or more `KnowledgeBase` instances and exposes a **capability-gated set of
tools** that can be bound to any supported agent framework.

Four tools are always built:

- `get_schemas()`: returns JSON with each backend's schema and metadata, including its declared
  `capabilities`. A backend whose `schema()` fails degrades to an `{"error": ...}` entry rather than failing
  the whole call.
- `read_kb(backend: str, query: str, limit: int = 3)`: retrieve from a specific backend, routed through
  `read()`.
- `write_kb(backend: str, text: str = "", source: str = "agent", query: str = "", params_json: str = "{}")`:
  persist to a backend.
- `get_all_kb_descriptions()`: short descriptions of each registered backend.

Up to three more are appended, each only when a registered backend declares the capability behind it, so an
agent's prompt never names an operation nothing can serve:

| Tool | Emitted when |
|---|---|
| `search_kb(backend, query, limit=3)` | some backend declares **both** `search` and `query` |
| `fetch_kb(backend, ids)` | some backend declares `fetch` |
| `browse_kb(backend, path="", limit=50)` | some backend declares `browse` |

`search_kb` has the narrowest gate, and it is checked **per backend**: for a search-only backend `read_kb`
already reaches `search()`, so the extra tool is only worth its slot in the prompt once one backend declares
`query` as well and `read()` therefore routes away from search. None of the built-in backends declares both,
so a stock application - including the `multi/` demo that registers Chroma, Neo4j and Starburst together -
gets the four base tools, while an OKF application gets six.

`write_kb` is the exception to gating. The original four tools are a compatibility promise, so it is always
emitted and its check happens per call: a write to a backend declaring `writable=False` returns a message
naming the backends that do accept writes, never an exception. `StarburstManager` is read-only in exactly
this sense - it declares `writable=False`, so `write_kb` declines it rather than the backend raising.

`fetch_kb` takes one identity, or several separated by commas - which is why a backend declaring `fetch`
must give every record a comma-free `metadata["id"]`. Those identities are what `format_results()` puts in
square brackets at the start of each line for a `fetch`-capable backend, so an agent can feed a search
result straight back into a fetch.

`KnowledgeBuilder` also supports a `semantic_map` parameter that resolves logical placeholders in agent-generated queries into backend-specific resource names at runtime. This is the key abstraction that keeps agents simple: they reason over stable, human-friendly tokens such as `<SHEETS_SOURCE>` or `<MONGO_SOURCE>` instead of memorizing changing catalog names, schema names, table names, or long physical paths.

In practice, the agent writes a query against the logical placeholder, and `KnowledgeBuilder` performs the translation immediately before the backend executes it. That means the agent can stay portable across environments while each deployment maps the same logical token to its own concrete target.

Resolution is not limited to query strings: `KnowledgeBuilder` resolves placeholders in `read_kb` and `search_kb` queries, in `write_kb` queries, in `browse_kb` paths, and in each comma-separated segment of a `fetch_kb` id list - so a token can stand for a namespace root as naturally as for a table.

Example:

```python
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager

v_db = ChromaManager(name="ChromaDB").add_schema({...})
g_db = Neo4jManager(name="Neo4jDB").add_schema({...})

kb_tools = KnowledgeBuilder([v_db, g_db]).build()
```

`kb_tools` is the output of `KnowledgeBuilder.build()`: a list of plain Python callables such as `get_schemas`, `read_kb`, and `write_kb`. Those callables are not yet agent tools on their own. The framework-specific adapter binds them into the agent runtime. In the OpenAI examples, that happens in one step with `tools=OpenAIToolBuilder.bind(knowledgeBuilder.build())`.



### `semantic_map`

1. What is `semantic_map`:
  - **Definition**: A mapping of stable, human-friendly placeholder tokens (keys) to concrete backend resource identifiers (values) used by `KnowledgeBuilder` at runtime.
  - **Form**: a plain Python dict where keys are tokens like `<SHEETS_SOURCE>` and values are backend-specific resource strings (SQL table references, DB paths, Trino/Starburst CALL syntax, etc.).

2. Purpose:
  - Decouples agent prompts from changing physical resource names so agent prompts remain portable across deployments.
  - Lets agents generate queries using logical tokens while the runtime binds those tokens to the correct backend targets.
  - Reduces agent hallucinations by centralizing backend-specific details in the deployment configuration.

3. Examples:
  - Vector store (Chroma): no physical table name needed; map to the backend name when helpful: `"<VECTOR_STORE>": "ChromaDB"`.
  - Graph (Neo4j): map to a named graph or connection string: `"<GRAPH>": "neo4j.default.graph"`.
  - Starburst/Trino (Sheets/Mongo): map logical placeholders to SQL FROM targets: `"<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'SHEET_ID'))"` or `"<MONGO_SOURCE>": "catalog.schema.table"`.

4. How to write a `semantic_map` (best practices):
  - Keep placeholders short and descriptive (e.g., `<SHEETS_SOURCE>`, `<MONGO_SOURCE>`).
  - Use one mapping per logical resource; avoid aliasing the same physical target under many keys.
  - Document expected query syntax in the backend `schema()` so agents can build correct queries (see demo examples for required templates).
  - Never expose credentials in `semantic_map` values; keep `semantic_map` purely as resource identifiers.
  - Make environment-specific overrides (CI, staging, prod) by supplying a different `semantic_map` at deployment time.

  #### KnowledgeBuilder example (semantic_map)

  The short example below shows the minimal steps to register backends, provide a `semantic_map`, build KB tools, and how the token replacement works at runtime. All explanatory notes are in comments.

  ```python
  # 1) Import the pieces
  from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
  from agentkernel.knowledgebase.chroma import ChromaManager
  from agentkernel.knowledgebase.neo4j import Neo4jManager

  # 2) Define (lightweight) backends and their schemas
  #    In real code you would supply full schema dictionaries as in the demos.
  v_db = ChromaManager(name="ChromaDB").add_schema({"description": "Vector store"})
  g_db = Neo4jManager(name="Neo4jDB").add_schema({"description": "Graph DB"})

  # 3) Define the semantic_map - agent prompts use the LEFT side tokens
  #    and the runtime replaces them with the RIGHT side physical targets.
  semantic_map = {
    "<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'SHEET_ID'))",  # Trino/Starburst wrapper
    "<MONGO_SOURCE>": "catalog.schema.clients",  # Example catalog.schema.table path
  }

  # 4) Create the KnowledgeBuilder with backends + semantic_map
  kb = KnowledgeBuilder([v_db, g_db], semantic_map=semantic_map)

  # 5) Build the KB tools (framework adapters bind these into agents)
  #    The exact return shape can be a list of callables; here we store as a variable.
  kb_tools = kb.build()

  # 6) Agent constructs a query using the logical placeholder token
  query = "SELECT client_name, status FROM <MONGO_SOURCE> WHERE status = 'active' LIMIT 5"

  # 7) At runtime, before the backend executes the SQL, KnowledgeBuilder
  #    replaces `<MONGO_SOURCE>` with `catalog.schema.clients` from `semantic_map`.
  #    Then `read_kb()` sends the resolved SQL to the correct Starburst backend.
  #    (In practice the agent calls the `read_kb` callable from `kb_tools`.)
  resolved_query = query.replace("<MONGO_SOURCE>", semantic_map["<MONGO_SOURCE>"])
  # read_results = read_kb("StarburstDB-mongo", resolved_query)

  # NOTE: Keep placeholders consistent in prompts and document required
  #       query templates in each backend's `schema()` to avoid runtime errors.
  ```


Example of wiring the KB tools into an agent:

```python
from agents import Agent
from agentkernel.openai import OpenAIToolBuilder

kb_router_agent = Agent(
  name="KB_Router_Agent",
  instructions="""
  You have access to multiple knowledge bases.
  Use get_schemas() to inspect them first, then decide which backend to read from or write to.
  Use read_kb for retrieval and write_kb for persistence.
  Where browse_kb, fetch_kb or search_kb are available, prefer browsing a namespace and fetching by
  identity over guessing search terms; get_schemas() tells you what each backend declares.
  Starburst declares itself read-only, so write_kb will decline it: route writes elsewhere.
  When a placeholder such as <MONGO_SOURCE> appears in a query, keep it unchanged in the prompt;
  the semantic_map will resolve it to the correct backend target at runtime.
  """,
  tools=OpenAIToolBuilder.bind(kb_tools),
)
```

Note: `kb_tools` used above is the result of calling `build()` on a `KnowledgeBuilder` instance (for example, `kb_tools = KnowledgeBuilder([...], semantic_map={...}).build()` or `kb_tools = kb.build()`); ensure you have created that variable before binding it into the agent to avoid confusion.


## KB Router Pattern

The recommended pattern is to build a **“knowledge base router” agent**:

1. **Inject tools**: Bind the knowledge base tools into the agent via the appropriate framework adapter.
2. **Describe backends**: Provide clear backend descriptions and schemas so the agent can tell what belongs in each store.
3. **Route explicitly**: In the instructions, tell the agent how to choose between KBs and which operation to use - relevance retrieval, a query-language statement, a fetch by identity, a namespace browse, or a write - including backend constraints (for example, Starburst declares itself read-only). The tool set itself varies with what is registered, so let the agent read the `capabilities` that `get_schemas()` reports rather than hard-coding assumptions about which tools exist.
4. **Keep placeholders logical**: Let the agent use tokens like `<SHEETS_SOURCE>` or `<MONGO_SOURCE>` while `semantic_map` handles the physical translation.
5. **Prefer a router agent for multi-KB setups**: One agent can inspect schemas and route requests, which reduces hallucination and keeps backend selection deterministic.

This pattern works the same across all supported agent frameworks (OpenAI Agents, LangGraph, CrewAI, Google ADK) because the tools are framework‑agnostic.

## Example: OpenAI KB Router

The repository includes OpenAI Agents SDK examples split by backend type:

- **Location**: `examples/cli/knowledgebase/openai`
- **Demos**:
  - `chromadb/` - semantic text only.
  - `neo4j/` - graph reads/writes using Cypher queries.
  - `starburst/` - SQL backends via Starburst/Trino.
  - `multi/` - combined router demo with all backends.
  - `okf/` - an Open Knowledge Format bundle of markdown files; no database required.
- **Agent**: `KB_Router_Agent`, created with clear routing rules, bound knowledge base tools from `KnowledgeBuilder`, and instructions to inspect schemas before choosing a backend, then route each query to the correct KB.

See the per-backend READMEs for step-by-step usage and routing behavior:
- `examples/cli/knowledgebase/openai/chromadb/README.md`
- `examples/cli/knowledgebase/openai/neo4j/README.md`
- `examples/cli/knowledgebase/openai/starburst/README.md`
- `examples/cli/knowledgebase/openai/multi/README.md`
- `examples/cli/knowledgebase/openai/okf/README.md`

## Custom KnowledgeBase Adapters

You can bring your own storage backend by subclassing `KnowledgeBase`. Any backend registered with `KnowledgeBuilder` (built-in or custom) is exposed to agents through the same `read_kb` / `write_kb` / `get_schemas` tools, plus `search_kb` / `fetch_kb` / `browse_kb` where the registered backends declare those capabilities.

### Minimal implementation

Three members stay abstract — `backend_name`, `connect`, and `get_description`. Everything else is
optional, and which of them you implement is fixed by the `KnowledgeCapabilities` you declare to
`super().__init__()`: an operation you do not declare raises `KnowledgeCapabilityError` instead of
returning an empty result, so the declaration and the implemented set must agree.

```python
from typing import Any, Iterable, List, Mapping
from agentkernel.knowledgebase import KnowledgeBase, KnowledgeCapabilities, Record


class MyBackend(KnowledgeBase):
    """Example custom knowledge base adapter."""

    def __init__(self) -> None:
        # Declare only what this backend actually supports.
        super().__init__(
            capabilities=KnowledgeCapabilities(
                kinds=["vector"],
                search=True,
                search_mode="semantic",
                writable=True,
            ),
        )

    @property
    def backend_name(self) -> str:
        return "MyBackend"  # Must be unique across registered backends

    def connect(self, **kwargs) -> None:
        # Establish any client / connection here
        self._client = ...  # your storage client

    def write(self, records: Iterable[Record], **kwargs) -> None:
        # Persist records; each record is {"text": str, "metadata": dict}
        for record in records:
            self._client.store(record["text"], record.get("metadata", {}))

    def search(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        # Return the most relevant records for the query
        raw = self._client.search(query, top_k=limit)
        return [{"text": r.text, "metadata": r.meta} for r in raw]

    def get_description(self) -> str:
        return "MyBackend stores domain-specific knowledge and supports full-text search."
```

Do not implement `read()`. It is concrete and routes on the declaration: a backend declaring `query`
receives the text as a statement, and every other backend receives it as a relevance `search`. That
routing is what lets the one `read_kb` tool serve every backend.

### The operation set

| Declare | Implement | Serves |
|---|---|---|
| `search` | `search(query, limit)` | relevance retrieval — `read_kb`, and `search_kb` when `query` is declared too |
| `query` + `query_language` | `query(statement, limit)` | query-language retrieval — `read_kb` |
| `fetch` | `fetch(ids)` | retrieval by identity — `fetch_kb` |
| `browse` | `browse(path, limit)` | namespace enumeration — `browse_kb` |
| `writable` | `write(records)` | persistence — `write_kb` |

At least one of them must be declared, and declaring `query` without a `query_language` (or a
`query_language` without `query`) is rejected in `__init__`.

### Registering the custom backend

Pass your backend to `KnowledgeBuilder` exactly as you would a built-in one:

```python
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder

my_backend = MyBackend().add_schema({
    "description": "Domain knowledge store",
    "usage": "Call read_kb with a natural-language query to retrieve matching entries.",
})

kb = KnowledgeBuilder([my_backend])
kb_tools = kb.build()
```

### Optional overrides

| Method | Default | When to override |
|---|---|---|
| `format_results(rows)` | Bullet-list of `text` + `source` | Custom display format for agent responses |
| `close()` | No-op | Release connections or flush write buffers |
| `add_schema(config)` | Merges dict into `_dynamic_schema` | Rarely needed; just call it rather than override |
| `schema()` | Returns `{"backend": name, ...schema_config, "capabilities": {...}}` | Rarely needed; override `_derived_schema()` instead |
| `_derived_schema()` | `{}` | Self-describe without `add_schema()`; declare `derives_schema=True` alongside it |
| `search(query, limit)` | Raises `KnowledgeCapabilityError` | Relevance retrieval; declare `search` alongside it |
| `query(statement, limit)` | Raises `KnowledgeCapabilityError` | Query-language retrieval; declare `query` + `query_language` |
| `fetch(ids)` | Raises `KnowledgeCapabilityError` | Retrieval by identity; declare `fetch`, and give every record a comma-free `metadata["id"]` |
| `browse(path, limit)` | Raises `KnowledgeCapabilityError` | Namespace enumeration; declare `browse` |
| `write(records)` | Raises `KnowledgeCapabilityError` | Persistence; declare `writable` |
| `read(query, limit)` | Routes to `query()` or `search()` | **Never** - the routing is what lets one tool serve every backend |

## Migration Notes

The capability model changes a few things an already-deployed agent can see. Each is intentional.

- **`schema()` output gains a `"capabilities"` key.** This changes the JSON `get_schemas()` returns to the
  agent. It is additive, but it is prompt-visible.
- **`StarburstManager`'s Trino schema name moved from `self.schema` to `self.db_schema`.** The `schema=`
  constructor keyword is unchanged, so no call site moves; only code reading `manager.schema` as a string
  must be updated. As a result `get_schemas()` now returns a real schema for Starburst backends instead of
  raising, because the attribute no longer shadows the inherited `schema()` method.
- **`KnowledgeBase.__init__` requires a `capabilities` argument** (`name` stays optional). A custom backend
  calling `super().__init__()` with no arguments must pass one - the only change here that is not backward
  compatible, and the reason capability declaration is not optional.
- **Undeclared operations raise `KnowledgeCapabilityError`, which is not a `NotImplementedError`.** In
  particular `StarburstManager.write` no longer raises `NotImplementedError`, so a caller catching the old
  type must be updated.
- **`write_kb` no longer writes `cypher_query` / `cypher_params` into record metadata**; it writes the
  generic `query` / `params` keys. `Neo4jManager.write` reads the generic keys and falls back to the old
  ones, so agent-issued writes are unaffected - but records already stored by Chroma carry the dead keys and
  are not migrated.
- **`build()` may return up to seven callables rather than four**, when registered backends declare `fetch`,
  `browse`, or both `search` and `query`.
- **`format_results()` prefixes `[<id>]`** for backends declaring `fetch`. No built-in backend other than
  `OKFManager` declares it, so existing output is unchanged.
- **`Neo4jManager.query` (formerly `read`) defaults to `limit=3`** instead of `limit=10`. `read_kb` always
  passes `limit`, so only direct callers see the difference.



## When to Use Knowledge Bases vs. Memory


Use **session memory and caches** when:
- Data is tied to a single conversation or short‑lived workflow.
- Content should influence the current LLM context only.
- You don’t need durable, cross‑session storage.

Use **knowledge bases** when:
- You need durable, reusable knowledge (docs, profiles, domain data).
- You want multiple agents or sessions to share the same information.
- You need specialized query capabilities (semantic search, graph queries).

You can also **combine** them:
- Fetch from a knowledge base, then cache results in the session’s volatile cache for fast reuse during a single request.

