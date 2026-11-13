# 14 · Memory and state

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Guard-Memory` (main), `Guard-Memory-Sessions`, `Guard-Memory-Threads`, `Guard-Memory-Attachments`, `Guard-Memory-ChangeBackend` |
| Canvas page | Guard |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static. Tabs are prototype links. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The pluggable stores behind the runtime and a browser for what they hold. The point to make visible: every
store is a configuration choice, and a multi-process deployment needs shared stores.

## Layout

- `AppShell` with Memory active. Page header "Memory and state", tabs "Stores", "Sessions · 18,204",
  "Threads · 4,112", "Attachments · 2.1 GB".
- Stores tab: a grid of store cards beside a narrow reference column.

## Content

**`Guard-Memory`** (Stores). Six cards, each with a title, a backend select, a connection line with a masked
host, a health dot, one metric and "Edit".

| Store | Backend | Connection | Metric |
|-------|---------|------------|--------|
| Session store | Redis | masked host, TTL 24 h | 18,204 active sessions |
| Thread store | Redis | same instance, prefix `ak:thread:`, TTL 30 d | 4,112 threads |
| Attachment store | Redis | prefix `ak:attachments:`, TTL 7 d | 2.1 GB · 9,310 files |
| Response store | Redis | chunk streaming supported · shared across processes | p95 wait 1.9 s |
| Queue transport | Amazon SQS | `ak-input.fifo` / `ak-output.fifo` · 5 consumers | depth 12 · 0 in DLQ, with a sparkline |
| Schedule store | DynamoDB | table `ak-schedules`, TTL off | 7 tasks |

Reference column:
- Card "Backends by store": a matrix with a mark where the backend is supported.

| Store | in_memory | Redis | Valkey | DynamoDB | Cosmos DB | Firestore |
|-------|-----------|-------|--------|----------|-----------|-----------|
| Session | yes | yes | yes | yes | yes | yes |
| Thread | yes | yes | yes | yes | yes | yes |
| Attachment | yes | yes | | yes | | |
| Response | yes | yes | yes | yes | | |
| Schedule | yes | yes | yes | yes | | |

- An `InlineBanner`: "Production runs several processes. Every store must be shared; in_memory is rejected at
  startup."
- Card "Bring your own": a field with the example `mypkg.stores.MySessionStore` and the helper "A dotted path
  to a SessionStore subclass".

**`Guard-Memory-Sessions`**
- A filter row (agent, "Active in: Last hour", search by session id) and a `DataTable`: Session id, Agent,
  Last active, Size, Framework state (chips "openai", "langgraph"), Paused runs. One row has "1 paused".
- The selected row opens a side panel "Session s_9f3c2a" with `JSONTree`s: "Framework state · openai",
  "Non-volatile cache" (keys `ak.paused_runs`, `agui_state`), "Volatile cache (cleared after each run)".
  Footer: a danger "Clear memory" and "Open in Playground".

**`Guard-Memory-Threads`**
- A `DataTable`: Thread name, User, Agent, Messages, Last message, Store. Names are auto-generated, for
  example "Damaged order refund A-8841".
- A "Naming" popover: "Model gpt-4o-mini", "Max length 80", "Explicit names lock the thread".

**`Guard-Memory-Attachments`**
- A grid of tiles: a thumbnail or file icon, an id such as `att_7a1c`, a media-type chip, the size and a TTL
  bar reading "expires in 5 d".

**`Guard-Memory-ChangeBackend`**
- A modal for the session store: a radio list "in_memory (development only)", Redis (selected), Valkey,
  DynamoDB, Cosmos DB, Firestore; fields URL, TTL, Prefix; a warning "Changing the store resets live
  sessions"; "Cancel" and "Apply".

## Behaviour

- Tabs link the four tab artboards. "Edit" on a store card opens `Guard-Memory-ChangeBackend`.
- "Open in Playground" goes to `Connect-Playground`.

## Tweaks

- `referenceColumn`: shown or hidden.

## Handoff notes

- The matrix reflects the repository at the time of writing. Check it against the store factories before
  build; it is data, not layout.
- Environment matters: this screen shows Production. Staging uses Valkey and NATS JetStream; Local uses the
  in-memory stores and transport.
