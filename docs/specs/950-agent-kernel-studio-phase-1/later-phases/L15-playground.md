# 15 · Playground

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Connect-Playground` (main), `Connect-Playground-Resolved`, `Connect-Playground-Empty`, `Connect-Playground-Structured`, `Connect-Playground-Voice` |
| Canvas page | Connect |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Working prototype (the approval and the event list) |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The chat tester for the running system, with history. It shows the full streamed event model: text, reasoning,
tool calls and results, a handoff between agents, a run paused for a human decision, and attachments. A panel
lists the raw stream events so a developer sees exactly what a client receives.

## Layout

- `AppShell` with Playground active, environment "Staging".
- Three columns: a session panel, the transcript, an events panel.

## Content

**Session panel.** Agent select "triage"; "New session"; a list of four sessions, each with an id, a relative
time and a first-message preview, "s_9f3c2a" selected. Options: "Execution mode: rest_sync", toggle "Stream
tokens (delta)" on, a "user_id" field holding "amitha", a chip "Multimodal on".

**Transcript.**
1. User: "Hi, I need a refund for order A-8841, it arrived damaged.", with an image attachment "photo.jpg ·
   1.2 MB".
2. triage: a collapsed `ReasoningBlock` "Reasoning · 2 steps"; a `ToolCallCard`
   `lookup_order({"order_id": "A-8841"})` with the result (status delivered, total 240.00, delivered
   2026-11-06) and "212 ms".
3. A `HandoffDivider`: "Handoff · triage → billing".
4. billing: an `ApprovalCard`, pending: "Approval required",
   `refund_payment(order_id="A-8841", amount=240.0)`, "Rule: amount > 200 · approvers: Support leads",
   "Approve", "Deny", "Cancel", and a field "Note to the agent (optional)".
5. billing, streaming: "Checking the refund policy for damaged items", with a cursor.

**Composer.** Placeholder "Message triage"; attach image, attach file and microphone controls; "Send". Chips
under it: "Streaming: delta", "Session: s_9f3c2a", "Tokens: 1,592".

**Events panel.** Tabs Events (active), Trace, Raw JSON. `StreamEventRow`s with a timestamp, a type chip and a
summary, in order: message_start; reasoning_start; reasoning_end; tool_call_start "lookup_order";
tool_call_args; tool_call_end; tool_call_result "212 ms"; step_start "handoff → billing"; text_delta × 14
(collapsed); tool_call_start "refund_payment"; run paused. Footer: "In 1,204 · Out 388 tokens",
"Latency 2.4 s", "Cost $0.021", link "Open in Traces".

## Behaviour (must work)

- "Approve" resolves the approval card and appends the result events. "Deny" and "Cancel" each resolve it
  with their own wording.
- The reasoning block expands and collapses.
- Clicking an event row highlights the matching part of the transcript.
- Selecting another session swaps the transcript. "Open in Traces" goes to `Operate-Traces`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Connect-Playground-Resolved` | first | The approval approved: "Approved by Amitha D. · 12:05", the call line, and the result "Refund of $240.00 issued · ref RF-20931". |
| `Connect-Playground-Empty` | first | No messages. The triage avatar, "Start a conversation with triage", and three suggestion chips: "Where is my order?", "I want a refund", "Compare plans". |
| `Connect-Playground-Structured` | second | The last agent message is a structured reply: a card "Structured reply · RefundDecision" with the JSON (order_id, approved, amount, reason) and a chip "application/json". |
| `Connect-Playground-Voice` | second | The composer as a voice row: a live waveform, a timer, "Stop", a "Transcript" toggle. Messages carry speaker icons. |

## Tweaks

- `eventsPanel`: shown or hidden. `sessionPanel`: shown or hidden.

## Handoff notes

- Event names are Agent Kernel's stream event types. A cancelled decision is different from a denied one;
  both exist.
- Structured replies are never streamed.
- This pending approval is BR-004 at work.
