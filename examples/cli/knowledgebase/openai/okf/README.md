# Open Knowledge Format Knowledge Base Demo

This example shows how to serve a knowledge base from a **directory of markdown files** — an
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
bundle — with no database and no service to run. The bundle is checked into this folder as
`bundle/`.

## What This Demo Teaches

1. How the `okf` configuration block gives named agents a knowledge base with no wiring code.
2. How the three roles — consumer, producer, curator — differ in tools and in instructions.
3. How write permission is scoped per `(agent, database)` rather than per agent.
4. How a backend that declares `search`, `fetch` and `browse` changes which tools an agent gets.
5. How `derives_schema=True` removes the need for an `add_schema()` call.

> These have been implemented in `config.yaml` and `demo.py` — please refer to those.

**`demo.py` imports nothing from `agentkernel.knowledgebase`.** No document store, no
`OKFManager`, no `KnowledgeBuilder`, no tool binding, and no instructions about how to navigate
a bundle. That absence is the point of the example, and `demo_test.py` asserts it. If you want
the wiring instead, see [Wiring It Yourself](#wiring-it-yourself-the-programmatic-path).

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

## The Configuration

`config.yaml` is the whole knowledge-base setup:

```yaml
okf:
  databases:
    warehouse:
      type: local
      uri: ./bundle
      description: "Analytics warehouse concepts, one markdown concept per table..."
      refresh_seconds: 300
      consumer: [KB_Consumer_Agent]
      producer: [KB_Producer_Agent]
      curator: [KB_Curator_Agent]
```

The block's presence is what enables the capability — there is no `enabled` flag. Each declared
database must name at least one agent, and each agent named gets its tools and its instructions
automatically.

> **The agent names are the contract.** They must match the `Agent(name=...)` values in
> `demo.py` exactly. An agent the block does not name simply receives no knowledge-base tools;
> nothing raises, nothing warns, and the agent will tell you it has no way to look anything up.
> If an agent seems to have lost its knowledge base, check the spelling here first.

## Run The Demo

```bash
python demo.py
```

The demo defines three agents. Switch between them in the CLI with `!select`:

```
!select KB_Consumer_Agent
What counts as revenue?

!select KB_Producer_Agent
Record this: the orders table is rebuilt nightly at 02:00 UTC.

!select KB_Curator_Agent
Review tables/customers.md and correct anything out of date.
```

Questions the consumer answers well:

- "What does the warehouse hold?"
- "What counts as revenue?"
- "Where is the orders data loaded from?"
- "Has the customers table been reviewed?"

Ask the consumer to write something and it will tell you it cannot: it holds only the
`consumer` role, so it never receives `write_kb` at all.

## The Bundle

```
bundle/
├── index.md              # the bundle's front page; carries okf_version: "0.2"
├── log.md                # change log; reserved, never a concept
├── tables/
│   ├── index.md          # a curated listing, honoured by browse("tables")
│   ├── orders.md         # human-reviewed; links to customers.md
│   └── customers.md      # machine-confirmed
├── datasets/
│   └── orders_db.md      # unverified; an invented `type`, kept verbatim
└── malformed.md          # no frontmatter — skipped with a diagnostic
```

`index.md` and `log.md` are reserved at **every** level, not just the root. A directory holding
an `index.md` is browsed by returning that file — a listing a human wrote beats one derived from
the filesystem. `datasets/` has no `index.md`, so browsing it returns a listing derived from the
manifest; both halves of that rule are reachable from this bundle.

The three concepts cover all three trust tiers, which are derived from `verified` and nothing
else: a `human:` actor makes `orders.md` **human-reviewed**, an automated actor makes
`customers.md` **machine-confirmed**, and an absent `verified` block leaves `orders_db.md`
**unverified**. No tier is ever filtered out — every concept answers every operation, and the
signal is passed to the agent to report.

`malformed.md` is checked in deliberately. A bundle containing a file that cannot be parsed must
still load: the file is skipped with an `unparseable_frontmatter` diagnostic, the other concepts
are unaffected, and the diagnostic is reported through `get_all_kb_descriptions` rather than
being swallowed.

## Walking The Bundle From The Agent's Side

The three tools this backend adds, in the order the agent is told to use them:

```text
browse_kb("OKF", "")            -> the bundle front page from index.md
browse_kb("OKF", "tables")      -> the curated listing in tables/index.md
browse_kb("OKF", "datasets")    -> a listing derived from the manifest
fetch_kb("OKF", "tables/orders.md")
                                -> the full body, plus metadata["links"] to customers.md
read_kb("OKF", "upstream postgres")
                                -> lexical ranking across the whole bundle
```

**Only `fetch_kb` reads a full body.** `browse_kb` and `read_kb` answer from a manifest that
holds frontmatter and a bounded token index, which is what keeps a large bundle affordable —
so a concept's complete text and its `links` are available only after a fetch.

## The Three Roles

| Agent | Role | Tools | What its prompt tells it |
|---|---|---|---|
| `KB_Consumer_Agent` | `consumer` | 6 (read only) | Navigate the bundle and answer from it |
| `KB_Producer_Agent` | `producer` | 7 | Add new knowledge as you learn it |
| `KB_Curator_Agent` | `curator` | 7 | Review, correct and maintain what is there |

**Producer and curator have identical permissions.** They differ only in the sentence Agent
Kernel appends to their instructions. The distinction is responsibility, not capability.

Permission is per `(agent, database)`, not per agent: an agent can be a producer of one bundle
and only a consumer of another, and both hold at once. With one database configured here, the
consumer's refusal is the visible half of that rule.

## Seven Tools

A producer or curator gets `get_schemas`, `read_kb`, `write_kb`, `get_all_kb_descriptions`,
`search_kb`, `fetch_kb` and `browse_kb`. The consumer gets the same set without `write_kb` —
withheld rather than refused per call, because an advertised tool it may never use is prompt
surface spent on a dead end.

All three gated tools are present because this backend declares `search`, `fetch` and `browse`.
A Neo4j or Starburst application declares none of them and gets the four base tools; a
Chroma-only application declares `search` and gets five. That is the capability model doing its
job: the agent's prompt only ever names operations that exist.

`read_kb` and `search_kb` both reach `search()` here, because OKF ranks and has no query
language. They are not redundant in what they promise — `read_kb` lets the backend decide how to
read the text, while `search_kb` always ranks and would refuse a backend that could not.

## Where Writes Land

`bundle/` is writable here, so the producer and curator write real files. Written concepts land
under **`bundle/generated/`** as ordinary OKF documents, stamped with a `generated:` block
naming the actor, and are visible to `browse`, `fetch` and `read` on the very next call — the
write updates the manifest directly rather than waiting for a refresh.

`write_kb` carries no title or path, so the backend takes both from the concept's own text: the
first line becomes the title and its slug becomes the filename, which is what lets a written
concept show its knowledge in a `browse` listing instead of just a generated path.

Those files are left where they land, so what the agent wrote is exactly what you can go and
read. `bundle/generated/` is git-ignored rather than checked in — clear it yourself when you
want a clean bundle again.

To make the bundle read-only instead, point the database at a store that says so. Capabilities
fold with `and`, so the more restrictive side always wins and `write_kb` reports the backend as
read-only. If a database names a `producer` or `curator` while its store is read-only, Agent
Kernel logs a warning naming both at startup — it does not refuse, because the same
configuration is legitimately correct wherever the bundle happens to be writable.

## What Happens At Startup

1. Agent Kernel reads the `okf` block and validates it: every database must name an agent, and
   no agent may be both `producer` and `curator` of the same database.
2. Each `Agent(...)` in `demo.py` is constructed. As it is, `SystemToolFactory` asks the OKF
   capability for that agent's tools and prompt section.
3. Nothing opens the bundle yet. The tool set is decided from configuration alone, so
   constructing ten agents over five bundles walks no store.
4. The first tool call an agent makes opens its bundle and walks it once. Every agent sharing
   that database shares the one walk and the one refresh cycle.

There is no `add_schema()` call anywhere. `OKFManager` declares `derives_schema=True` and
answers `get_schemas()` from the bundle itself — the version, the concept count, the types in
use, the top-level namespaces and any diagnostics.

## Wiring It Yourself: The Programmatic Path

The configuration block is a convenience, not a replacement. Everything under it stays a public
API, so an application that wants to build the tier itself still can:

```python
from agentkernel.knowledgebase import KnowledgeBuilder, LocalDocumentStore, OKFManager
from agentkernel.openai import OpenAIToolBuilder

backend = OKFManager(
    LocalDocumentStore("./bundle", writable=False),
    name="OKF",
    description="Open Knowledge Format bundle describing the analytics warehouse.",
)
builder = KnowledgeBuilder([backend])

agent = Agent(
    name="KB_Router_Agent",
    model="gpt-4.1-mini",
    instructions="...your own navigation protocol...",
    tools=OpenAIToolBuilder.bind(builder.build()),
)
```

Choose this path when the bundle location is computed at runtime, when one agent needs a tool
set the roles do not describe, or when you want to write the navigation instructions yourself.
Choose the config path otherwise — it is less code and the protocol ships maintained.

Do not use both for the same agent. If an agent is named in the `okf` block *and* has
knowledge-base tools bound by hand, it ends up carrying two sets of identically named tools;
Agent Kernel logs a warning naming the collisions and attaches anyway, since silently ignoring
your configuration would be worse.

## Run Tests

```bash
uv run pytest -s demo_test.py
```

## Serving The Same Bundle From S3

`OKFManager` composes whatever `DocumentStore` it is handed, so moving the bundle to an object
store is a store swap, not a backend change:

```yaml
okf:
  databases:
    warehouse:
      type: s3
      uri: s3://my-bucket/bundles/warehouse
      consumer: [KB_Consumer_Agent]
```

`type` and `uri` must agree — `type: local` with an `s3://` uri is refused at startup naming the
database — so the redundancy is a check rather than a second source of truth. `type` may also be
a dotted path to your own `DocumentStore` subclass, which then defines what its `uri` means.

The same swap on the programmatic path is one argument:

```python
OKFManager(DocumentStore.from_uri("s3://my-bucket/bundles/warehouse"), name="OKF")
```

`from_uri` also accepts a plain path or a `file://` URL, so one configuration string covers
local-in-development and S3-in-production. The S3 store needs the `aws` extra.
