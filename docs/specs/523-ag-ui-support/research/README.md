# #523 research index

Supporting investigation for "Agent Kernel support for AG-UI" (issue #523, JIRA AK-155). The issue
body is one line — *"Agentic UI (AG-UI can be one adapter) https://docs.ag-ui.com/introduction"* —
so the framing question ("**one** adapter of what?") is itself part of what this research answers.

| File | Topic | One-line takeaway | Status |
|---|---|---|---|
| [`ag-ui.md`](ag-ui.md) | AG-UI protocol survey + AK gap analysis + four integration routes | AK already produces the *text* half of AG-UI and already discards the rest at the runner boundary; the real cost is not the HTTP surface, it is enriching `Runner.stream`'s `str` contract | Complete; no code written |
| [`a2ui.md`](a2ui.md) | A2UI protocol survey + four routes for AK to emit it | A2UI is a *payload*, not a transport — it needs no new AK frontend, it needs a prompt/catalog capability plus a reply type, and AK already has the machinery for both | Complete; no code written |
| [`decision-log.md`](decision-log.md) | Decisions taken in review, the then-intended five-PR delivery shape (now six — see `design.md`), and the verified code facts behind them | Read this before writing `spec.md`: it records what was settled (and what was reversed), and §4 lists the load-bearing `path:line` facts so they are not re-derived | Living; **partly superseded by `design.md`** — see the status note at the top of the file before relying on any entry |

## How the two relate

They are complementary, not competing, and this is the single most useful thing to carry into
`design.md`:

- **AG-UI** standardizes *the event stream* — how an agent tells a UI "a message started", "a tool
  is running", "state changed".
- **A2UI** standardizes *one payload* that can travel inside such a stream — a declarative JSON
  description of a UI, rendered against the client's own component catalog.

A2UI's own documentation names AG-UI as one of its supported transports, so "AG-UI can be one
adapter" reads naturally as: AK grows an agentic-UI surface, AG-UI is the first protocol on it, and
A2UI is a payload that can ride it (or ride AK's existing A2A surface independently).

## Method and honesty notes

- **Codebase claims** (`path:line`) were verified by reading the files on `develop` at
  commit `1693d2e0`, 2026-08-14. One claim was verified by execution rather than reading and is
  flagged as such in `ag-ui.md` (`StreamChunk` silently dropping `session_id`).
- **Protocol claims** come from vendor documentation fetched 2026-08-14 and are marked
  **[docs]**. Nothing was installed, imported, or run: no `ag-ui-protocol` or `a2ui-agent-sdk`
  package was exercised locally, no reference frontend was driven end to end. Every event name,
  field name, and package name below should be re-verified against the pinned version before it
  is written into `spec.md`.
- Both protocols are pre-1.0 and moving (AG-UI's own docs carry a "Draft" event category; A2UI is
  at v0.9.1 with v1.0 a release candidate). Version pinning is a design decision, not a detail.
