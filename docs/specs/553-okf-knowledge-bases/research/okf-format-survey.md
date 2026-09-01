# Open Knowledge Format (OKF) — format survey

Supporting research for `../design.md` (issue #553). Captures what OKF is, what it requires of a
consumer, and which of its properties drive the AK design decisions.

**Verification status.** The v0.2 specification and the announcement blog were read on 2026-08-31 via
web fetch, and the summaries below are that reading, not a verbatim transcription. Every normative
statement marked **[SPEC]** must be re-checked against the specification text verbatim before it is
implemented — the design's conformance requirements are only as good as this re-check.

Sources:
- Announcement: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing
- Specification + reference implementations: https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf

## 1. What OKF is

- A vendor-neutral, open **format** for curated, agent-consumable knowledge. Explicitly *not* a
  platform, an SDK, an ontology, or a query language.
- It formalizes the "LLM-wiki" pattern: knowledge a team already writes in markdown, given just
  enough structure that an agent can navigate it mechanically.
- Current published version is **v0.2**; v0.1 bundles remain consumable with fallbacks.

## 2. Physical shape

A bundle is a directory tree of markdown files:

```
sales/
├── index.md                # reserved: directory listing / progressive disclosure
├── log.md                  # reserved: chronological change history
├── datasets/
│   ├── index.md
│   └── orders_db.md
├── tables/
│   ├── orders.md
│   └── customers.md
└── references/             # conventional: mirrored external material, scripts, code
```

- **The file path is the concept's identity.** `/tables/orders.md` *is* the id. There is no separate
  id field, and nothing outside the path is authoritative.
- `index.md` and `log.md` are **reserved filenames [SPEC]** — they are not concept documents.
- Distribution is by ordinary means: a git repo, a tarball, a mounted directory, an object-store
  prefix. Nothing in the format assumes a database.

## 3. Concept documents

YAML frontmatter + markdown body.

```markdown
---
type: BigQuery Table                       # the ONLY required field [SPEC]
title: Orders
description: One row per completed customer order.
resource: https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders
tags: [sales, revenue]
status: stable                             # draft | stable (default) | deprecated
stale_after: 2026-12-01T00:00:00Z
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-05-28T14:30:00Z }
verified:
  - { by: "human:jsmith", at: 2026-06-02T09:00:00Z }
sources:
  - { id: bq_meta, resource: "https://…", title: "BigQuery INFORMATION_SCHEMA" }
---

# Schema
| Column | Type | Description |
|--------|------|-------------|
| `customer_id` | STRING | FK to [customers](/tables/customers.md). |
```

Frontmatter families:

| Family | Fields | Purpose |
|---|---|---|
| Identity | `type` (required), `title`, `description`, `resource`, `tags` | what the concept is |
| Provenance | `sources[]` (`resource` required; `id`, `title`, `author`, `usage_count`, `last_modified`) | what it was derived from |
| Trust | `generated: {by, at}`, `verified: [{by, at}]` | who produced/checked it |
| Lifecycle | `status`, `stale_after` | whether it should still be believed |
| Computation | `runtime`, `parameters`, `computation`, `executor`, `attester` | only for `type: Attested Computation` |

- **Actor convention [SPEC]**: `<producer>/<version>` for agents, `human:<id>` for people,
  `process:<id>` for automation. Consumers detect human review by the `human:` prefix.
- **Trust tiers [SPEC]** derive from `verified`: absent → *unverified*; present with no `human:`
  actor → *machine-confirmed*; present with a `human:` actor → *human-reviewed*. Advisory signals,
  never grounds for rejection.
- Conventional body headings with defined meaning: `# Schema`, `# Examples`, `# Computation`.
- Per-claim attribution uses markdown footnotes keyed to `sources[].id`.

## 4. The graph is markdown links

Relationships are ordinary markdown links, in two forms **[SPEC]**:

- **Bundle-absolute**: `[customers](/tables/customers.md)` — resolved from the bundle root.
- **Relative**: `[sibling](./other.md)`.

Link *semantics* live in the surrounding prose, not in the link. There is no typed edge, no
relationship vocabulary, and no graph database. Path-valued frontmatter fields (`resource`,
`sources[].resource`, `computation`) accept absolute URLs, bundle-relative paths, or relative paths.

## 5. Conformance — what binds a consumer

A bundle is conformant if every non-reserved `.md` file has parseable YAML frontmatter containing a
non-empty `type`, and reserved files follow their structure **[SPEC]**.

The consumer obligations are the load-bearing part for AK, because they are all *tolerance* rules:

- **MUST** treat a bare `verified` mapping as a one-element list.
- **MUST NOT** reject a concept for missing optional fields or an unknown `type`.
- **MUST NOT** reject a bundle for a missing `index.md`, a broken link, or unknown frontmatter keys.
- **MUST** surface failed attestations rather than silently dropping them.
- **SHOULD** derive trust tiers and staleness only from the specified fields.

Read together: **a strict OKF reader is a non-conformant OKF reader.** Anything unrecognised is
carried through, not refused. This is why the design's OKF backend degrades per-document instead of
failing a load.

## 6. Versioning

- `<major>.<minor>`; minor bumps are backward-compatible additions.
- A bundle may declare its target version as `okf_version: "0.2"` in the **bundle-root `index.md`**
  frontmatter — the only frontmatter permitted in an index file.
- v0.1 → v0.2 breaking changes a reader must absorb:
  - `timestamp` was replaced by `generated: {by, at}`.
  - A body `# Citations` list was replaced by the `sources` frontmatter family.

## 7. Attested Computation

A concept type (`type: Attested Computation`) describing a runnable, verifiable computation: a
`runtime`, typed `parameters`, the computation itself (inline under `# Computation` or referenced by
the `computation` path field), an `executor` that produces a receipt, and an `attester` that
deterministically checks the receipt. The informative consumer workflow is discover → load →
parameterize → execute → attest → gate (refuse failed attestations, warn on staleness).

**Takeaway for AK:** executing these is a *sandbox* concern, not a knowledge-base concern — the
executor runs arbitrary code. The design therefore reads such concepts like any other concept and
declares execution a non-goal, rather than growing an execution path inside the KB layer.

## 8. Reference implementations (prior art)

- **Enrichment agent (producer):** walks a BigQuery dataset, drafts one concept per table/view, then
  runs a second LLM pass to add citations, schemas, and join paths. Confirms the intended pattern is
  *agents write OKF*, not just read it — the design keeps a conformant write path for this reason.
- **Static HTML visualizer (consumer):** renders any bundle as an interactive graph from a single
  self-contained file, with no backend.
- Sample bundles published for GA4 e-commerce, Stack Overflow, and Bitcoin public datasets — usable
  as fixtures for the conformance tests.

## 9. Why this shapes the AK design

| OKF property | Consequence for AK |
|---|---|
| Format, not storage — a bundle is just a directory | Representation must be separable from the byte store, so one OKF reader serves local FS and S3 |
| Path is identity | Retrieval needs a *fetch-by-id* and a *browse* operation, which today's single `read(query)` hole cannot express |
| Only `type` is required; producers invent types | The schema an agent is shown must be **derived** from the bundle, not hand-registered per deployment |
| Consumers must tolerate everything | Degrade per document; never fail a bundle load on a bad file |
| Trust/lifecycle frontmatter is advisory | Surface tier/staleness to the agent as signals; never filter on them silently |
| Attested Computation executes code | Out of scope for the KB layer; belongs to the sandbox capability |
