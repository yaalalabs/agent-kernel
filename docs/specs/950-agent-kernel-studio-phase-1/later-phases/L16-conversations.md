# 16 · Conversations

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Connect-Conversations` (main), `Connect-Conversations-Empty`, `Connect-Conversations-Rename` |
| Canvas page | Connect |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static with links |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The inbox of persistent conversation threads across channels and the API. The business owner reads what the
agents said; the operator finds a session, its user and its runs.

## Layout

- `AppShell` with Conversations active.
- Three columns: a thread list, the thread view, a details panel.

## Content

**Thread list.** A search field; channel filters (All, Slack, WhatsApp, Gmail, REST, LiveKit); an agent
select; filter chips "Has attachments", "Paused", "Last 7 days" (active). Rows show a channel icon, a title, a
one-line preview, a time and a user chip.

| Title | Channel | Note |
|-------|---------|------|
| Damaged order refund A-8841 | Slack | selected |
| Invoice copy for October | Gmail | |
| Plan upgrade questions | WhatsApp | unread |
| API: session s_77ab | REST | |
| Voice call 3 min | LiveKit | |

A "Load more" control at the bottom.

**Thread view.** Title "Damaged order refund A-8841" with a rename control. Chips: "session s_9f3c2a", "user
amitha@acme.example", "agents triage → billing", "Slack · #support", "14 messages". Messages:
1. User text with an attachment card "photo.jpg · image/png · 1.2 MB · att_7a1c".
2. triage reply.
3. A `HandoffDivider`: "Handoff · triage → billing".
4. A resolved `ApprovalCard`: "refund_payment($240.00) approved by Priya N. · 12:05".
5. billing confirms the refund, reference "RF-20931".
6. User: "Thank you".
A read-only bar at the bottom: "Replies are sent by the agent. Open in Playground to continue this session."

**Details panel.** Card "Thread": Session id s_9f3c2a (copy control), User id, Group id, Created
(9 Nov 2026 12:01), Store "Redis · TTL 30 d", Messages 14, Attachments 1. Card "Linked runs": three rows
(time, agent, status, duration), each with a "Trace" link. Footer: "Open in Playground", "Export JSON", a
danger "Delete thread".

## Behaviour

- "Trace" goes to `Operate-Traces`. "Open in Playground" goes to `Connect-Playground`.
- The rename control opens `Connect-Conversations-Rename`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Connect-Conversations-Empty` | first | No threads. An `EmptyState`: "No threads yet. Threads are recorded when a thread handler is mounted.", with a link "Enable in Memory". |
| `Connect-Conversations-Rename` | second | A popover on the title: a field with the current name, a toggle "Lock name (disable auto-naming)", "Cancel" and "Save". |

## Tweaks

- `detailsPanel`: shown or hidden.

## Handoff notes

- Threads belong to clients that talk to the agent directly. Messaging platforms keep their own history, so
  whether channel conversations appear here as threads is a product decision (see Open details).
- Thread listings are paginated by cursor; "Load more" is the pattern, not page numbers.

## Open details

- Agent Kernel records threads for direct clients, not for messaging integrations. This brief shows Slack,
  WhatsApp and Gmail threads in the inbox. Decide whether the product adds that, or whether the inbox shows
  direct threads plus a per-channel run history.
