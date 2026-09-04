# Open Knowledge Format Knowledge Base Demo

This example shows how to serve a knowledge base from a **directory of markdown files** — an
[Open Knowledge Format](https://openknowledgeformat.org) bundle — with no database and no
service to run. The bundle is checked into this folder as `bundle/`.

## What This Demo Teaches

1. How to compose a `DocumentStore` (where the bytes live) with `OKFManager` (how they are read).
2. How a backend that declares `fetch` and `browse` changes which tools the agent is given.
3. How `derives_schema=True` removes the need for an `add_schema()` call.
4. How a store's writability folds into the backend's capability declaration.
5. How to bind the resulting tools into an OpenAI Agent and run it from the Agent Kernel CLI.

> These have been implemented in `demo.py` — please refer to that.

## Prerequisites

- Python 3.12 or 3.13
- `uv` installed
- `OPENAI_API_KEY` exported in your shell

Example:

```bash
export OPENAI_API_KEY="your-key-here"
```

No knowledge-base extra is needed. Parsing an OKF bundle uses `pyyaml`, which is a core
dependency of `agentkernel`.

## Setup

Run from this folder:

```bash
./build.sh
```

Use local source code from this repository (instead of the published package):

```bash
./build.sh local
```

## Run The Demo

```bash
python demo.py
```

When the CLI starts, ask questions such as:

- "What does the warehouse hold?"
- "What counts as revenue?"
- "Where is the orders data loaded from?"
- "Has the customers table been reviewed?"

## The Bundle

```
bundle/
├── index.md              # the bundle's front page; carries okf_version: "0.2"
├── log.md                # change log; reserved, never a concept
├── tables/
│   ├── index.md          # a curated listing, honoured by browse("tables")
│   ├── orders.md         # human-reviewed; links to customers.md
│   └── customers.md      # unverified
├── datasets/
│   └── orders_db.md      # an invented `type`, kept verbatim
└── malformed.md          # no frontmatter — skipped with a diagnostic
```

`index.md` and `log.md` are reserved at **every** level, not just the root. A directory holding
an `index.md` is browsed by returning that file — a listing a human wrote beats one derived from
the filesystem. `datasets/` has no `index.md`, so browsing it returns a listing derived from the
manifest; both halves of that rule are reachable from this bundle.

`malformed.md` is checked in deliberately. A bundle containing a file that cannot be parsed must
still load: the file is skipped with an `unparseable_frontmatter` diagnostic, the other concepts
are unaffected, and the diagnostic is reported through `get_all_kb_descriptions` rather than
being swallowed.

## Walking The Bundle From The Agent's Side

The three tools this backend adds, in the order the agent is told to use them:

```text
browse_kb("OKF", "")            -> the bundle front page from index.md
browse_kb("OKF", "<TABLES>")    -> the curated listing in tables/index.md
browse_kb("OKF", "datasets")    -> a listing derived from the manifest
fetch_kb("OKF", "tables/orders.md")
                                -> the full body, plus metadata["links"] to customers.md
read_kb("OKF", "upstream postgres")
                                -> lexical ranking across the whole bundle
```

`<TABLES>` is a `semantic_map` token registered in `demo.py`. `KnowledgeBuilder` resolves it
before the call reaches the backend, so the same agent instructions work against a bundle whose
physical layout differs between environments.

**Only `fetch_kb` reads a full body.** `browse_kb` and `read_kb` answer from a manifest that
holds frontmatter and a bounded token index, which is what keeps a large bundle affordable —
so a concept's complete text and its `links` are available only after a fetch.

## Six Tools, Not Seven

`KnowledgeBuilder.build()` returns `get_schemas`, `read_kb`, `write_kb`,
`get_all_kb_descriptions`, `fetch_kb` and `browse_kb`.

`fetch_kb` and `browse_kb` are present because this backend declares `fetch` and `browse`.
`search_kb` is **absent**: its gate needs a backend declaring both `search` and `query`, and an
OKF bundle has no query language. Nothing is lost — `read_kb` reaches `search()` directly. A
Chroma-only application gets the four base tools and neither of the two added here. That is the
capability model doing its job: the agent's prompt only ever names operations that exist.

## Read-Only, And How To Change It

`demo.py` builds the store with `writable=False`. Capabilities fold with `and`, so the more
restrictive side always wins: a read-only store beats a backend willing to write. `write_kb`
therefore reports the backend as read-only rather than adding files.

To let the agent contribute concepts, change one keyword:

```python
LocalDocumentStore("./bundle", writable=True)
```

Written concepts land under `bundle/generated/` as ordinary OKF documents, stamped with a
`generated:` block naming the producer, and are visible to `browse`, `fetch` and `read` on the
very next call — the write updates the manifest directly rather than waiting for a refresh.

## What Happens In demo.py

1. `LocalDocumentStore` points at `./bundle`; `OKFManager` wraps it and walks it once.
2. `KnowledgeBuilder` creates the six tools, gated on what the backend declares.
3. `OpenAIToolBuilder.bind(...)` attaches those tools to the router agent.
4. The agent is registered in `OpenAIModule`.
5. `CLI.main()` starts the interactive chat loop.

There is no `add_schema()` call anywhere in `demo.py`. `OKFManager` declares
`derives_schema=True` and answers `get_schemas()` from the bundle itself — the version, the
concept count, the types in use, the top-level namespaces and any diagnostics.

## Run Tests

```bash
uv run pytest -s demo_test.py
```

## Serving The Same Bundle From S3

`OKFManager` composes whatever `DocumentStore` it is handed, so moving the bundle to an object
store is a store swap, not a backend change:

```python
OKFManager(DocumentStore.from_uri("s3://my-bucket/bundles/warehouse"), name="OKF")
```

`from_uri` also accepts a plain path or a `file://` URL, so one configuration string covers
local-in-development and S3-in-production. The S3 store needs the `aws` extra.
