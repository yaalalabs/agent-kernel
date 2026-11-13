# 11 · Knowledge bases

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Build-Knowledge` (main), `Build-Knowledge-Graph`, `Build-Knowledge-SQL`, `Build-Knowledge-Add` |
| Canvas page | Build |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static. The four top cards are prototype links between the artboards. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The knowledge layer agents read from and write to as tools. Each backend declares what it supports, and the
UI shows only those capabilities. Open Knowledge Format bundles add per-agent roles.

## Layout

- `AppShell` with Knowledge active. Page header "Knowledge" with a primary "Add knowledge base".
- A row of cards, one per knowledge base, plus an "Add" card.
- Below, a three-column detail area for the selected knowledge base.

## Content

**Top cards** with `CapabilityChip`s. A one-line legend under the row: "Search = full-text or vector · Query =
Cypher or SQL · Fetch = by id · Browse = by path · Writable = agents may add records".

| Card | Backend | Capabilities |
|------|---------|--------------|
| Help Center (selected) | Open Knowledge Format bundle · `s3://acme-kb/help` · 412 concepts | Search, Fetch, Browse, Writable |
| Product Graph | Neo4j · Cypher | Query, Writable |
| Orders | Starburst / Trino · SQL | Query, Read-only |
| Tickets | ChromaDB · vector | Search, Writable |

**`Build-Knowledge`** (Help Center)
- Left, card "Bundle": a breadcrumb "help / returns" and a `FileTree` with folders billing, shipping and
  returns (open), and files refund-window.md (selected), exchanges.md, damaged-items.md. Each file has a trust
  tier: "verified" or "draft".
- Middle, card "refund-window.md": title "Refund window"; chips "verified", "updated 3 days ago", "curator:
  kb-researcher"; the document body (a heading, two paragraphs and a list about 30-day refunds); "Edit" and
  "History".
- Right, card "Agent roles": a matrix of agents by role. kb-researcher is consumer, producer and curator;
  billing and triage are consumers. Helper "Read scope is per agent and database".
- Right, card "Test search": the query "refund window after 30 days" and three results with scores 0.91, 0.84
  and 0.77, a title and a one-line excerpt.

**`Build-Knowledge-Graph`** (Product Graph)
- Left, card "Schema": node labels Product, Plan, Feature, Region and the relationship types.
- Middle, card "Query": a Cypher editor with
  `MATCH (p:Product)-[:HAS_FEATURE]->(f) RETURN p.name, f.name LIMIT 10` and a result table.
- Right: the same "Agent roles" card.

**`Build-Knowledge-SQL`** (Orders)
- Left, card "Tables": orders, order_items, refunds, with column counts.
- Middle: a SQL editor with a SELECT over refunds grouped by reason, a result table, and a "Read-only" chip in
  the card header.
- Right: "Agent roles" with the write column disabled.

**`Build-Knowledge-Add`**
- A modal with the backend choices: "OKF bundle (local or S3)" (selected), "ChromaDB", "Neo4j", "Starburst /
  Trino", "Amazon S3 documents", "Custom (Python class path)"; fields "Name" and "URI"; "Cancel" and
  "Connect".

## Behaviour

- Selecting a top card goes to that backend's artboard. "Add knowledge base" opens `Build-Knowledge-Add`.

## Tweaks

- `rolesCard`: matrix or list.

## Handoff notes

- Capabilities are declared per backend instance (search, query, fetch, browse, write). Render chips and
  panels from that declaration; never assume a backend can do something.
- The role matrix enforces BR-008. The read-only backend enforces BR-012.
