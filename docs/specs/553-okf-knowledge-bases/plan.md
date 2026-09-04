# #553: Open Knowledge Format support and the knowledge-base architecture refactor — Implementation Plan

Orders [`spec.md`](spec.md) into iterations. Every component in that document appears in exactly one
iteration below; nothing here restates its detail — each step cites the spec section that fixes it.

Two conventions that shape the ordering:

- **Unit tests land with the code they cover**, per `ak-dev-testing-conventions`, so every iteration is
  independently verifiable. Iteration 8 adds only what cannot be written earlier: the reusable
  `KnowledgeBaseContract`, its run against every backend, and the scale envelope.
- **`KnowledgeBase.__init__` requiring `capabilities` (behavioural change 13) is what couples the early
  iterations.** The reshaped ABC and the three existing backends must land together — the moment the
  base takes a required argument, `ChromaManager()` / `Neo4jManager()` / `StarburstManager()` raise
  `TypeError`. That is iteration 2, and it is deliberately the largest.

Every iteration ends green on `cd ak-py && uv run pytest -k knowledgebase` and on
`make lint-check-all` (the command `code-quality.yml` runs). Expect unrelated e2e failures on a full
local `pytest` without CI credentials (`AGENTS.md:103-108`).

## Iteration 1: Capability model and errors

- **Goal:** `KnowledgeCapabilities`, the two record `TypedDict`s, and the three error types exist and
  are tested. Pure addition — no existing module imports them yet, so the branch is unchanged in
  behavior.
- **Files:** `knowledgebase/model.py` (new), `knowledgebase/errors.py` (new),
  `ak-py/tests/test_knowledgebase_model.py` (new).
- **Steps:**
  1. `model.py` — `KnowledgeCapabilities` with the nine fields, plus `KnowledgeMetadata` /
     `KnowledgeRecord` as `total=False` `TypedDict`s (spec § `knowledgebase/model.py`). No cross-field
     validator on the model: both invariants belong to `KnowledgeBase.__init__`, which knows the
     backend name.
  2. `errors.py` — `KnowledgeError`, `KnowledgeCapabilityError` (the `sandbox/errors.py:20-39` shape,
     *not* subclassing `NotImplementedError`), `KnowledgePathError` (spec § `knowledgebase/errors.py`,
     addition A).
- **Verify:** `uv run pytest tests/test_knowledgebase_model.py` — defaults, `model_dump()` shape, and
  that constructing a `KnowledgeCapabilities` alone never validates.

## Iteration 2: The reshaped ABC and the three existing backends

- **Goal:** the capability contract is live end to end for the backends that exist today. `read()` is
  concrete and routes; `search`/`query`/`fetch`/`browse`/`write` are optional; `schema()` derives and
  carries `capabilities`; Starburst's `schema` attribute/method collision is fixed.
- **Files:** `knowledgebase/base.py`, `knowledgebase/chroma.py`, `knowledgebase/neo4j.py`,
  `knowledgebase/starburst.py`, `ak-py/tests/test_knowledgebase_base.py` (new), and the
  `validate_capabilities` half of `ak-py/tests/test_knowledgebase_model.py`.
- **Steps:**
  1. `base.py` — `__init__(capabilities, name=None)`, module-level `validate_capabilities`, the five
     optional operations, concrete `read()` routing on `capabilities.query`, `_derived_schema()` +
     relaxed `schema()` guard with `capabilities` written last and unoverridable, and the `fetch`-gated
     `format_results` prefix (spec § `knowledgebase/base.py` and its two subsections; addition G).
     `read`/`write` stop being abstract; `backend_name`/`connect`/`get_description` stay abstract.
  2. `chroma.py` — declare `kinds=["vector"], search=True, search_mode="semantic", writable=True`;
     rename `read` → `search`.
  3. `neo4j.py` — declare `kinds=["graph","structured"], query=True, query_language="cypher",
     writable=True`; rename `read` → `query` with the first parameter `statement`; make `write` read
     `metadata["query"]`/`params` **with the `cypher_*` fallback** and skip a record carrying neither.
     The fallback lands **before** iteration 3 drops the `cypher_*` emission, so neither iteration
     leaves agent-issued Neo4j writes broken.
  4. `starburst.py` — declare `kinds=["structured"], query=True, query_language="sql",
     writable=False`; move `self.schema` → `self.db_schema` and update its three readers
     (`starburst.py:111,116,204`) leaving the `schema=` constructor keyword alone; rename `read` →
     `query`; `write` raises `KnowledgeCapabilityError`. Leave `_execute`'s `[]`-on-failure as is
     (spec § `StarburstManager`).
- **Verify:** `uv run pytest tests/test_knowledgebase_base.py tests/test_knowledgebase_model.py`, plus
  the four existing examples still constructing their backends — behavioural changes 1-4, 9-11, 14-16
  all land here and each has an assertion.

## Iteration 3: `KnowledgeBuilder` — capability-gated tools

- **Goal:** the agent surface reflects the capability model: up to seven tools, gated on the registered
  set, with generic write metadata.
- **Files:** `knowledgebase/knowledgebuilder.py`, `ak-py/tests/test_knowledgebase_builder.py` (new).
- **Steps:**
  1. Add `search_kb`, `fetch_kb`, `browse_kb`, appended in that order after the existing four, each
     emitted only on its gate (`search_kb` needs a backend declaring **both** `search` and `query`);
     capability mismatches return the actionable string, never an exception (spec §
     `knowledgebase/knowledgebuilder.py`).
  2. Extend semantic-map resolution to `search_kb` queries, `fetch_kb` ids (per segment, after the `,`
     split) and `browse_kb` paths.
  3. `get_schemas` gains the per-backend `try/except` its sibling already has; `write_kb` stops setting
     `cypher_query`/`cypher_params`; capability reads go through `getattr(backend, "capabilities",
     None)` with a warning for a backend that never called `super().__init__()`.
- **Verify:** `uv run pytest tests/test_knowledgebase_builder.py` — the riskiest consumer, so the
  gating matrix, tool order, and the `write_kb` metadata assertion are all here (behavioural changes
  5-7).

## Iteration 4: Storage axis — `DocumentStore`

- **Goal:** bytes at paths, containment enforced in one place, local and S3 stores interchangeable
  through `from_uri`. Nothing consumes it yet.
- **Files:** `knowledgebase/store/{__init__,base,local,s3}.py` (new),
  `ak-py/tests/knowledgebase_contracts.py` (new — `DocumentStoreContract` only; *as built* under
  `tests/` rather than the `knowledgebase/testing.py` this plan originally named),
  `ak-py/tests/test_knowledgebase_stores.py` (new).
- **Steps:**
  1. `store/base.py` — the ABC, `normalise_relative` called by every entrypoint and by every path
     `list()` emits, `read_prefix_bytes` with its default, `write_bytes` refusal on a non-writable
     store, and `from_uri`'s five branches including the mandatory `python:` discriminator (spec §
     `knowledgebase/store/`; addition C).
  2. `store/local.py` — `realpath` root with a `ValueError` on a non-directory, `writable=None`
     probing, traversal-time containment (`os.walk(followlinks=False)` + `commonpath`), and
     `sorted()` global lexicographic `list()`.
  3. `store/s3.py` — `require_extra("aws", …)`, injectable client, paginated `list`, `NoSuchKey`/404 →
     `FileNotFoundError`, ranged-GET `read_prefix_bytes`, declared `writable`.
  4. `knowledgebase_contracts.py` — `DocumentStoreContract` in the `SandboxProviderContract`
     (`sandbox/testing.py:130`) shape. The file imports `pytest`, so it is excluded from every lazy
     export map; it lives under `ak-py/tests/` because it is not a published helper.
- **Verify:** `uv run pytest tests/test_knowledgebase_stores.py` — the contract over a real `tmp_path`
  and a fake boto3 client, plus the containment matrix and the `a/z.md` vs `ab/b.md` ordering case.

## Iteration 5: Representation axis — OKF parsing

- **Goal:** `bytes`/`str` in, `OKFConcept`/`OKFBundle` out, tolerant by specification. No store, no
  network.
- **Files:** `knowledgebase/okf/{__init__,model,parser}.py` (new),
  `ak-py/tests/test_knowledgebase_okf_parser.py` (new).
- **Steps:**
  1. `okf/model.py` — `TrustTier`, `OKFDiagnostic`, `OKFConcept`, `OKFBundle`, and the exhaustive
     diagnostic-code table (spec § `okf/model.py`).
  2. `okf/parser.py` — frontmatter split (`yaml.safe_load` only), the tolerance rules, trust from
     `verified` alone, staleness from `stale_after` against an injected `now`, and link extraction in
     both specified forms (spec § `okf/parser.py`).
  3. Reserved-file rules: `index.md` and `log.md` at **every** level; root-only `okf_version`
     frontmatter; an `index.md` elsewhere carrying frontmatter gets a diagnostic and is still used
     (spec § `index.md` and `log.md` handling — verification-gate outcome 2).
- **Verify:** `uv run pytest tests/test_knowledgebase_okf_parser.py` — every diagnostic code reachable,
  the v0.2-only assertions (`timestamp` → `extra`, `# Citations` stays body text), and the test that
  fails if the module pulls in `urllib`/`httpx` or `knowledgebase.store`.

## Iteration 6: `DocumentKnowledgeBase` and `OKFManager`

- **Goal:** OKF is a working backend — `search`/`fetch`/`browse`/`write` over a `DocumentStore`, with
  the manifest, its refresh, and write-through visibility.
- **Files:** `knowledgebase/document.py` (new), `knowledgebase/okf/manager.py` (new),
  `ak-py/tests/test_knowledgebase_okf_manager.py` (new).
- **Steps:**
  1. `document.py` — store composition, `store.writable` folded in with `and`, `_read_document`'s
     `FileNotFoundError` → `None` mapping, `close()` delegation (spec § `knowledgebase/document.py`).
  2. `OKFManager.__init__` — capabilities from the injected store, producer resolved once via
     `importlib.metadata` with the `agentkernel/unknown` fallback.
  3. The manifest: bounded `read_prefix_bytes` walk with a full-read fallback, retained frontmatter +
     `body_tokens`, `max_concepts` truncation over the store's lexicographic order (spec § Manifest;
     addition F).
  4. `_ensure_manifest` — blocking initial load, non-blocking refresh under `threading.Lock`,
     whole-object swap, failed refresh serving stale and resetting the clock, `reload()` (spec §
     Refresh and concurrency).
  5. The five operations plus `_derived_schema`, `get_description` (diagnostics surfaced), and the
     `format_results` override (spec § Operations). `write()` is write-through and refuses a `,` in a
     bundle path.
- **Verify:** `uv run pytest tests/test_knowledgebase_okf_manager.py` — ranking determinism,
  browse-at-`tables/`, write-through with `refresh_seconds=None`, one walk under two concurrent
  boundary-crossing callers, and that nothing is ever filtered on trust or staleness.

## Iteration 7: Public exports and the OKF example

- **Goal:** the documented import works, optional SDKs stay lazy, and the whole capability-gated tool
  set is demonstrated end to end.
- **Files:** `knowledgebase/__init__.py` (rewritten), `ak-py/tests/test_knowledgebase_exports.py`
  (new), `examples/cli/knowledgebase/openai/okf/` (new).
- **Steps:**
  1. `__init__.py` — the PEP 562 `_LAZY_EXPORTS` map of `deployment/aws/__init__.py:13-66`, with the
     `TYPE_CHECKING` mirror block. The three SDK-backed managers are deliberately not exported, and
     neither is any contract suite (spec § `knowledgebase/__init__.py`; behavioural change 8).
  2. The example, in its siblings' shape (`build.sh`, `demo.py`, `demo_test.py`, `__init__.py`,
     `pyproject.toml`, `README.md`) plus the checked-in `bundle/` — root and `tables/` `index.md`, a
     `log.md`, three trust tiers, an unknown `type`, and one malformed file. `demo.py` calls no
     `add_schema()` (that is what `derives_schema=True` buys) and registers a `semantic_map` for the
     bundle root. `pyproject.toml` follows the sibling convention: runtime `agentkernel[cli,openai]`,
     dev group `agentkernel[test]`, and **no KB extra** — `pyyaml` is core.
  3. `README.md` walks `browse_kb` → `fetch_kb` → `search_kb` against real bundle paths.
- **Verify:** `uv run pytest tests/test_knowledgebase_exports.py` (every `__all__` name resolves;
  `chromadb`/`neo4j`/`trino`/`boto3` stay out of `sys.modules`; the `overview.md:353` import works
  verbatim), then `./build.sh local && uv run pytest` inside the example.

## Iteration 8: Contract suite and scale envelope

- **Goal:** the contract every backend is held to is reusable and actually run, and the declared
  10,000-concept envelope is enforced by CI rather than asserted in prose.
- **Files:** `ak-py/tests/knowledgebase_contracts.py` (extended), `ak-py/tests/test_knowledgebase_contract.py` (new),
  `ak-py/tests/test_knowledgebase_okf_envelope.py` (new).
- **Steps:**
  1. `knowledgebase_contracts.py` — `KnowledgeBaseContract` and `FakeKnowledgeBase` alongside the
     existing `DocumentStoreContract`; neither contract class is named `Test*`, and the module itself
     is not named `test_*`.
  2. `test_knowledgebase_contract.py` — the contract run against `FakeKnowledgeBase` in four capability
     shapes, `OKFManager` over a real local bundle, and the three existing backends with
     `chromadb.PersistentClient`, `neo4j.GraphDatabase.driver`, and `trino.dbapi.connect`
     monkeypatched. The `schema()`-is-callable assertion is the regression guard for the Starburst
     collision.
  3. `test_knowledgebase_okf_envelope.py` — a generated 10,000-concept bundle; all 10,000 kept, and
     `tracemalloc` allocations attributable to `_walk()` under 50 MB (not RSS).
- **Verify:** `cd ak-py && uv run pytest -k knowledgebase` green, then `make lint-check-all`.

## Iteration 9: Sync docs and skills

Each surface below was checked against the branch; line numbers are where the stale text is today.

- **Docs:**
  - `docs/docs/advanced/knowledge-bases.md:15` (`### KnowledgeBase`) — the five-operation set replaces
    the `read`/`write` pair; `KnowledgeCapabilities`; `OKFManager` in the backend list.
  - same file `:47` (`## KnowledgeBuilder and Tools`) — the three new tools and their gating.
  - same file, **new section** — the OKF backend, `DocumentStore` local-vs-S3, `from_uri`, and the
    `refresh_seconds`/`max_concepts` cost statement (one ranged GET per concept per refresh per pod).
  - same file `:203-235` (`### Minimal implementation`) — **required, not cosmetic**: the example
    subclass defines no `__init__`, so it stops constructing under behavioural change 13 (spec
    deviation E).
  - same file `:253-260` (`### Optional overrides`) — add `_derived_schema()`; note `schema()` now
    always carries `capabilities`.
  - `docs/docs/core-concepts/overview.md:351-358` — the documented import starts working; the
    `read`/`write` bullet list becomes the operation set.
  - Both pages call out the two prompt-visible migrations: `schema()` gaining `"capabilities"`, and
    `StarburstManager.schema` → `db_schema`.
- **Skills:**
  - `.agents/skills/ak-dev-new-knowledgebase-integration/SKILL.md` — the heaviest rewrite: step 2's
    `super().__init__()` at `:52` now needs `capabilities=`; step 3 "Record Contract" (`:83`) predates
    `KnowledgeMetadata`; step 4 (`:92-98`) tells authors to raise `NotImplementedError` for a read-only
    backend; and there is no capability-declaration or `DocumentStore` step at all. Add both, plus the
    `KnowledgeBaseContract` requirement to step 9 (`:149`) and the checklist (`:174`).
  - `.agents/skills/ak-dev-architecture/SKILL.md:520-521` — the `KnowledgeBase` member list and the
    four-tool `KnowledgeBuilder` line; `:714-716` — the directory tree gains `model.py`, `errors.py`,
    `document.py`, `store/`, `okf/` (not `testing.py` — the contracts live under `ak-py/tests/`).
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:353-419` — the knowledge-base capability
    section: the new tools, and OKF as a backend option. Its custom-backend pointer at `:418-419` stays
    valid.
- **Verified as needing no update:** no `AKConfig` section, so nothing under `ak-deployment/` or the
  Helm chart changes; no framework adapter, `Runtime`, or `Session` surface moves; no existing test
  file references the knowledge-base tier (grep over `ak-py/tests/` and `e2e/`), so **no patch target
  moves anywhere in the suite**. `.agents/skills/ak-dev-testing-conventions` **does** need a change,
  contrary to this plan's original claim: its `## Test File Organization` table inventories individual
  test modules and already names the other two reusable contracts, so the eleven new
  `test_knowledgebase*` modules and `ak-py/tests/knowledgebase_contracts.py` belong in it.
- **Verify:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before
  merge to catch any surface this list missed, then `make lint-check-all`.
