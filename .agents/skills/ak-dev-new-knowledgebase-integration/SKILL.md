---
name: ak-dev-new-knowledgebase-integration
description: >
  Step-by-step guide for adding a new knowledge base backend to Agent Kernel.
  Use this skill when you need to integrate a new storage system with the
  KnowledgeBase interface and expose it through KnowledgeBuilder tools.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Knowledge Base Integration

Use this skill to add a new knowledge base backend under `ak-py/src/agentkernel/knowledgebase/`.

This applies when you are integrating any durable source not already covered by:
- `ChromaManager` (semantic vector search)
- `Neo4jManager` (graph relationships)
- `StarburstManager` (read-only SQL via Trino)
- `OKFManager` (Open Knowledge Format markdown bundles, over a local directory or S3)

If the new source is **documents addressed by path**, do not start from scratch: compose a
`DocumentStore` instead (step 4a).

## Prerequisites

- Understand architecture and contribution patterns from `.agents/skills/ak-dev-architecture/SKILL.md`
- Understand existing knowledge base APIs:
  - `ak-py/src/agentkernel/knowledgebase/base.py` (the ABC, `read()` routing, `schema()`)
  - `ak-py/src/agentkernel/knowledgebase/model.py` (`KnowledgeCapabilities`, record typing)
  - `ak-py/src/agentkernel/knowledgebase/errors.py` (the error hierarchy)
  - `ak-py/src/agentkernel/knowledgebase/knowledgebuilder.py` (tool gating)
  - `ak-py/src/agentkernel/knowledgebase/document.py` and `store/base.py` (document-shaped backends)
  - `ak-py/src/agentkernel/knowledgebase/okf/manager.py` (the reference document backend)
- Have provider credentials and a local/dev test instance for the target backend

## Step-by-Step

### 1. Create Backend Module

Create a new file:

`ak-py/src/agentkernel/knowledgebase/<backend>.py`

Use lowercase file names (for example `qdrant.py`, `milvus.py`, `elasticsearch.py`).

### 2. Subclass `KnowledgeBase`

Implement a concrete class that extends `KnowledgeBase`:

```python
from typing import Any, Iterable, List, Mapping

from .base import KnowledgeBase, Record
from .model import KnowledgeCapabilities


class MyBackendManager(KnowledgeBase):
    def __init__(self, name: str = "", description: str | None = None, **kwargs):
        # Declare only what this backend actually supports: an undeclared operation
        # raises KnowledgeCapabilityError rather than returning an empty result.
        super().__init__(
            capabilities=KnowledgeCapabilities(
                kinds=["vector"],
                search=True,
                search_mode="semantic",
                writable=True,
            ),
            name=name,
        )
        self.name = name
        self.description = description or "my backend"
        self._client = None
        self.connect(**kwargs)

    @property
    def backend_name(self) -> str:
        return self.name if self.name else "mybackend"

    def connect(self, **kwargs) -> None:
        # Initialize backend client and verify connectivity.
        self._client = ...

    def write(self, records: Iterable[Record], **kwargs) -> None:
        for record in records:
            text = str(record.get("text", "")).strip()
            metadata = dict(record.get("metadata", {}))
            if not text:
                continue
            # Persist text + metadata using backend-native API.
            self._client.store(text=text, metadata=metadata)

    def search(self, query: str, limit: int = 3, **kwargs) -> List[Mapping[str, Any]]:
        rows = self._client.search(query=query, limit=limit)
        return [{"text": row["text"], "metadata": row.get("metadata", {})} for row in rows]

    def get_description(self) -> str:
        return f"{self.backend_name}: {self.description}"
```

`super().__init__(capabilities=...)` is required — the base takes no zero-argument form. Pass `name`
too so a rejected declaration names your backend rather than the class.

### 2a. Declare the Right Capability Set

`backend_name`, `connect` and `get_description` are the only abstract members. Each retrieval and
write operation is optional, and the declaration decides which ones you must implement:

| Declare | Implement | Serves |
|---|---|---|
| `search` | `search(query, limit)` | `read_kb`, and `search_kb` when `query` is declared too |
| `query` + `query_language` | `query(statement, limit)` | `read_kb` |
| `fetch` | `fetch(ids)` | `fetch_kb` |
| `browse` | `browse(path, limit)` | `browse_kb` |
| `writable` | `write(records)` | `write_kb` |
| `derives_schema` | `_derived_schema()` | `get_schemas` without an `add_schema()` call |

Two fields are descriptive rather than gating: `kinds` is an open taxonomy (`vector`, `structured`,
`graph`, `document`, …) and `search_mode` (`"semantic"` / `"lexical"`) is advisory — it does not imply
`search`, and declaring `search` does not require it.

Rules `KnowledgeBase.__init__` enforces:

- At least one of `search` / `query` / `fetch` / `browse` / `writable` must be `True`.
- `query=True` requires a `query_language` (`"cypher"`, `"sql"`, …), and a `query_language` requires
  `query=True`.

`KnowledgeBase.validate_capabilities(capabilities, subject)` is a static method, so a declaration can
be checked without constructing a backend — which is how the contract suite exercises it.

Never implement `read()`. It is concrete and routes on the declaration — to `query()` when `query` is
declared, to `search()` otherwise — which is what lets one `read_kb` tool serve every backend.

Note the narrow `search_kb` gate: it is checked **per backend**, so it appears only when one backend
declares both `search` and `query`. A search-only backend needs no extra tool because `read_kb` already
reaches `search()`.

If the backend derives its own schema, declare `derives_schema=True` **and** return a non-empty mapping
from `_derived_schema()`; the contract suite fails a backend that declares one without the other.
`schema()` writes `capabilities` last and unoverridably, so a deployment cannot contradict the
declaration through `add_schema()`.

### 3. Respect the Record Contract

All reads must return normalized rows compatible with `KnowledgeBuilder`:
- `{"text": str, "metadata": dict}`

All writes accept the same shape through `write(records=[...])`.

If the provider result is not in this shape, normalize inside `search()` / `query()` / `fetch()` / `browse()`.

`model.py` names the shape in two `TypedDict`s — `KnowledgeRecord` (`text`, `metadata`) and
`KnowledgeMetadata` (`id`, `source`, `title`, `kind`, `trust`, `stale`, `links`). **They are
documentation-only.** `Record = Mapping[str, Any]` stays the annotation on every signature, nothing
validates them at runtime, and a backend is free to carry keys beyond the conventional set. Use them to
decide what to *name* your metadata, not as a schema to enforce.

One key is load-bearing: a backend declaring `fetch` must put a comma-free `id` in every record's
metadata. `format_results()` prefixes each line with it so the agent can feed a result straight back
into `fetch_kb`, and `fetch_kb` splits its `ids` argument on `,`. `KnowledgeBaseContract` asserts this;
nothing checks it at runtime.

### 4. Define Backend Constraints Explicitly

If the backend is read-only, say so in the declaration and implement nothing:

```python
super().__init__(
    capabilities=KnowledgeCapabilities(kinds=["structured"], query=True, query_language="sql", writable=False),
    name=name,
)
```

`KnowledgeBase.write()` then raises `KnowledgeCapabilityError(backend_name, "write")` on its own, and
`KnowledgeBuilder` gates `write_kb` before it ever reaches you. Do not override `write()` to raise —
that only duplicates the base — and never silently ignore writes. The same holds for every other
operation: leave undeclared ones unimplemented rather than raising by hand.

Raise into the hierarchy in `errors.py`, not out of it:

- `KnowledgeError` is the base every knowledge-base failure subclasses.
- `KnowledgeCapabilityError` is an undeclared operation. It is deliberately **not** a
  `NotImplementedError`: that would be indistinguishable from an unimplemented abstract method, whereas
  this is a declaration mismatch the tool boundary is expected to catch and explain.
- `KnowledgePathError` is a path that escapes a store namespace or is unusable as an identity.

Finding nothing is **not** a failure. A read matching no records returns `[]`; a document that cannot be
parsed is skipped with a diagnostic. Reserve exceptions for failures of the machinery.

### 4a. Document-Shaped Backends: Compose a `DocumentStore`

If your records are documents at paths, subclass `DocumentKnowledgeBase` rather than `KnowledgeBase`
and let a `DocumentStore` supply the bytes. That splits the two axes — storage and representation — so
one backend serves the same collection from a local directory in development and an object store in
production, with no code change. `OKFManager` (`okf/manager.py`) is the reference implementation.

```python
class MyDocBackend(DocumentKnowledgeBase):
    def __init__(self, store: DocumentStore, name: str = "") -> None:
        super().__init__(
            store=store,
            capabilities=KnowledgeCapabilities(kinds=["document"], search=True, fetch=True, browse=True, writable=True),
            name=name,
        )
```

What the base gives you, and what it does not:

- **Writability folds with `and`.** The store's `writable` is intersected with your declaration, so the
  more restrictive side wins: a read-only store beats a backend willing to write. This is why
  capabilities are per instance, not per class.
- **`_read_document(path)` maps absence to `None`**, not an exception — `FileNotFoundError` and other
  `OSError`s (a browse record fed back into `fetch` reaches `open()` on a directory) become a logged
  warning and an empty answer. `KnowledgePathError` deliberately propagates.
- **Containment is the store's obligation, not yours.** `..` segments, absolute paths, and symlinks
  escaping a local root are refused on access and skipped during traversal. Decide per operation what
  to do with the refusal — dropping one path out of a `fetch` list and refusing a whole `write` are
  different answers — but never re-implement the check.
- **Configuration is a single string.** `DocumentStore.from_uri()` accepts a bare path, `file://`,
  `s3://bucket/prefix`, and `python:pkg.mod.ClassName` for a bring-your-own store. Take a
  `DocumentStore` in your constructor; do not take a path and build the store yourself.

### 5. Add Robust Connection Handling

- Validate required configuration fields in `connect()`
- Fail fast with clear `ValueError` messages for missing settings
- Add reconnection logic when the provider client commonly drops stale sessions
- Implement `close()` if the backend has sockets, cursors, or open sessions

### 6. Add Optional Dependencies

Update `ak-py/pyproject.toml` with a new optional dependency group:

```toml
[project.optional-dependencies]
mybackend = [
    "provider-sdk>=x.y.z",
]
```

Keep dependency groups narrow and provider-specific.

Two cases the template does not cover:

- **A pure-Python backend may need no extra at all.** The OKF backend adds none — `pyyaml` is a core
  dependency. Do not invent an extra for a group that would be empty.
- **The extra belongs where the import is.** `boto3` arrives through `S3DocumentStore` and the existing
  `aws` extra, not through the backend that composes it.

Then decide whether the backend belongs in `knowledgebase/__init__.py`'s `_LAZY_EXPORTS`. The rule is
the reason `ChromaManager` / `Neo4jManager` / `StarburstManager` are deliberately **not** exported: a
module that imports its SDK at module import would make that SDK a hard requirement the moment an agent
touched the name, even lazily. Export the name only if importing your module pulls no optional
dependency; otherwise leave callers to import it from its own module, and say so in its docstring. If
you do export it, add the `TYPE_CHECKING` mirror entry too.

### 7. Add Usage Example

Add or update example code under `examples/cli/knowledgebase/openai/` showing:
- backend initialization
- schema registration via `.add_schema(...)` — **unless** the backend declares `derives_schema=True`,
  in which case the example should contain no `add_schema()` call at all; that absence is what the flag
  buys, and the OKF demo demonstrates it
- `KnowledgeBuilder([...], semantic_map=...)`
- tool binding using `OpenAIToolBuilder.bind(kb.build())`
- which tools the app actually gets, and why — the capability-gated set is the part a reader cannot
  infer from the code

Reference pattern:
- `examples/cli/knowledgebase/openai/chromadb/demo.py`
- `examples/cli/knowledgebase/openai/neo4j/demo.py`
- `examples/cli/knowledgebase/openai/starburst/demo.py`
- `examples/cli/knowledgebase/openai/okf/demo.py` (document store composition, `derives_schema`, gating)
- `examples/cli/knowledgebase/openai/multi/demo.py`

### 8. Add/Update Documentation

Document the backend in:
- `docs/docs/advanced/knowledge-bases.md`
- `docs/docs/core-concepts/overview.md` (if backend list appears there)

Include:
- when to use this backend
- the capability declaration, and which tools it therefore adds or withholds
- required environment variables, or the store URI for a document-shaped backend
- schema/query guidance for routing agents

Also add the example to the demo and README lists in `docs/docs/advanced/knowledge-bases.md` and
`docs/docs/examples/overview.md`, and to the backend enumerations in `README.md`, `ak-py/README.md`,
`docs/docs/intro.md` and `docs/docs/installation.md` — those lists are the ones that silently go stale.

### 9. Add Tests

**Unit tests under `ak-py/tests/` are the primary requirement**, and a contract run is mandatory. The
tier has eleven `test_knowledgebase*` modules to model yours on; the demo test beside the example
(`examples/cli/knowledgebase/openai/*/demo_test.py`) is additional, not a substitute.

**1. Subclass the reusable contract.** `ak-py/tests/knowledgebase_contracts.py` holds
`KnowledgeBaseContract`, `DocumentStoreContract` and the dependency-free `FakeKnowledgeBase` the
knowledge-base contract is proven against. Register your backend in
`ak-py/tests/test_knowledgebase_contract.py`:

```python
from knowledgebase_contracts import KnowledgeBaseContract

class TestMyBackendContract(KnowledgeBaseContract):
    @pytest.fixture
    def knowledge_base(self):
        return MyBackendManager(...)   # mock the provider client
```

Every assertion is gated on your own declaration, so the contract adapts to what you declared rather
than demanding a shape you did not claim. Override the input hooks (`search_query`, `query_statement`,
`browse_path`, `write_probe`, `declared_ids`) when the defaults do not suit the backend.

The contract lives under `tests/` rather than in the package **on purpose** — it is a suite this repo
holds its own backends to, not a published helper for out-of-tree authors. There is no
`agentkernel.knowledgebase.testing` module; do not tell users to import one. Note also that the
contract classes are deliberately not named `Test*` and the module is not named `test_*`, so pytest
collects neither on its own — keep that convention if you add one.

**2. Add a `DocumentStoreContract` subclass** if you added a store, as
`ak-py/tests/test_knowledgebase_stores.py` does for the local and S3 stores.

**3. Add a module for the backend's own behavior.** Cover:
- successful connection path, and input validation for missing config
- each operation you declared, and that its records normalize to `text` + `metadata`
- that an operation you did **not** declare raises `KnowledgeCapabilityError` (the base does this; the
  test guards against an accidental override)
- `backend_name` uniqueness assumptions and descriptive output
- `_derived_schema()` returning a non-empty mapping, if you declared `derives_schema`

**4. If you exported the name**, extend `ak-py/tests/test_knowledgebase_exports.py` — it asserts every
`__all__` entry resolves and that no optional SDK lands in `sys.modules` on import. That test is the
gate a new export has to pass.

Prefer mocked provider clients to avoid flaky external calls.

### 10. Verify KnowledgeBuilder Compatibility

Validate that your backend works with `KnowledgeBuilder.build()` and tools:
- `get_schemas()` returns your backend schema, and it carries a `capabilities` key matching your
  declaration — written last by `schema()`, so `add_schema()` cannot contradict it
- `get_all_kb_descriptions()` includes your backend's description
- `read_kb()` routes correctly to your backend name, reaching `query()` if you declared `query` and
  `search()` otherwise
- `write_kb()` behaves as expected (or returns a readable capability message, not an exception)
- the gated tools appear exactly when they should: `fetch_kb` if you declared `fetch`, `browse_kb` if
  you declared `browse`, `search_kb` only if you declared both `search` and `query`
- if you declared `derives_schema`, `get_schemas()` works with no `add_schema()` call anywhere

## Checklist

- [ ] New backend module created under `ak-py/src/agentkernel/knowledgebase/`
- [ ] Class subclasses `KnowledgeBase` — or `DocumentKnowledgeBase` over a `DocumentStore` for
      document-shaped knowledge — and implements `backend_name`, `connect`, `get_description`
- [ ] `super().__init__(capabilities=..., name=name)` declares only what the backend actually supports,
      and every declared operation is implemented — the declaration and the implemented set agree
- [ ] No `read()` override; no hand-written raise for an undeclared operation
- [ ] Read results normalized to `{"text", "metadata"}` records, with a comma-free `id` if `fetch` is
      declared
- [ ] `derives_schema` and a non-empty `_derived_schema()` either both present or both absent
- [ ] Connection handling includes validation and clear errors, raised into the `KnowledgeError` hierarchy
- [ ] Optional dependency group added to `ak-py/pyproject.toml` — or deliberately none
- [ ] Export decision made for `knowledgebase/__init__.py` (`_LAZY_EXPORTS` plus the `TYPE_CHECKING`
      mirror), and it pulls no optional SDK
- [ ] Example added/updated under `examples/cli/knowledgebase/openai/`
- [ ] Documentation updated in the knowledge base docs, and the backend added to the enumerations that
      list backends
- [ ] `KnowledgeBaseContract` subclass registered in `ak-py/tests/test_knowledgebase_contract.py` and
      green (plus `DocumentStoreContract` for a new store)
- [ ] Unit tests added under `ak-py/tests/` for connect, each declared operation, and constraints
- [ ] `ak-py/tests/test_knowledgebase_exports.py` extended if the name is exported
- [ ] Backend verified through `KnowledgeBuilder` tools, including which gated tools appear
