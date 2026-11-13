# 09 · Agents: list and detail

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Agents-List`, `Agents-Detail-Instructions` (main), `Agents-Detail-Tools`, `Agents-Detail-Hooks`, `Agents-Detail-RunOptions`, `Agents-Detail-OutputSchema`, `Agents-Detail-HumanInTheLoop` |
| Canvas page | Build |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static. Tabs are prototype links between the detail artboards. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

Everything Agent Kernel configures per agent, on one page with tabs: instructions and the handoff description,
bound tools with approval flags, pre- and post-hooks including the fixed system hooks, framework-native run
options with reserved keys, the structured-output schema and the human-in-the-loop policy.

## Layout

- `AppShell` with Agents active. Breadcrumb "Acme Labs / support-triage / Agents / billing".
- Page header: a back link "Agents"; the LangGraph mark, "billing", chips "LangGraph" and "claude-sonnet-4-5",
  status "Deployed · Production"; actions "Open in canvas", "Test in Playground" and a disabled "Save changes".
- A tab bar: Instructions, Tools · 2, Hooks · 2, Run options, Output schema, Human in the loop.
- Each tab: a wide main column and a narrow right column.

## Content

**`Agents-List`**
- A `DataTable`: Agent, Framework, Model, Tools, Handoffs, Status. Rows triage, billing, kb-researcher from
  the fixture. A primary "New agent" and the AI button "Describe an agent".

**`Agents-Detail-Instructions`**
- Card "System instructions": a toolbar (AI button "Improve with AI", a character count "1,284", "Test") and
  the code editor with eight lines of a support billing prompt: the role, the refund rules, when to escalate,
  the tone.
- Card "Handoff description", helper "Shown to triage when deciding to hand off, and published on this agent's
  A2A card", text "Handles refunds, invoices and payment questions. Can issue refunds up to $200 without
  approval."
- Right column: "Model" (select, a temperature slider at 0.2, toggle "Streaming" on); "Receives handoffs from"
  (chip "triage" and an add control); "A2A agent card" (a JSON preview: name, description, a URL ending in
  `/a2a/billing`, skills "refunds" and "invoices", and a link "Open card JSON").

**`Agents-Detail-Tools`**
- A `DataTable`: Tool, Signature, Source (Project, System, MCP), Requires approval (toggle).

| Tool | Signature | Source | Requires approval |
|------|-----------|--------|-------------------|
| lookup_order | `lookup_order(order_id: str) -> dict` | Project | off |
| refund_payment | `refund_payment(order_id: str, amount: float) -> str` | Project | on, condition `amount > 200` |
| analyze_attachments | `analyze_attachments(attachment_ids, prompt)` | System | off |

- A "Bind tool" button above the table.

**`Agents-Detail-Hooks`**
- Two ordered lists with drag handles, "Pre-hooks" and "Post-hooks". System hooks carry a lock and cannot be
  reordered or removed.
- Pre-hooks: "Input guardrail · system", "Multimodal · system", "Sandbox · system", then "RAG context
  injector" (editable). For billing the injector is not attached; show an "Add hook" control.
- Post-hooks: "Output guardrail · system", "A2UI labelling · system", then "Signature footer", with a chip
  "filters stream events".

**`Agents-Detail-RunOptions`**
- A `KeyValueEditor`: `config.callbacks`, `config.recursion_limit = 50`.
- A locked row `config.configurable.thread_id` with the note "Reserved by Agent Kernel".
- A toggle "Compute per run with a factory", off. Helper "Options are passed to LangGraph's invoke as-is".

**`Agents-Detail-OutputSchema`**
- Left: the code editor with a Pydantic class `RefundDecision` (`order_id: str`, `approved: bool`,
  `amount: float`, `reason: str`). Right: its JSON Schema preview.
- An `InlineBanner`: "Structured output replies are not streamed".

**`Agents-Detail-HumanInTheLoop`**
- Card "Pause policy": a rule row "When refund_payment is called with amount > 200"; a select "Approvers:
  Support leads"; checkboxes for the decisions Approve, Deny, Cancel; a field "Message sent on cancel".
- Right column, card "Paused runs · 2": two rows with session ids and "Review" links.

## Behaviour

- Tabs link the six detail artboards. The back link goes to `Agents-List`; a row there opens the detail.
- "Open in canvas" goes to `Builder-Canvas`. "Test in Playground" and "Review" go to `Connect-Playground`.

## Tweaks

- `agent`: billing (default) or triage, to check the page with an OpenAI Agents SDK agent.

## Handoff notes

- Reserved run-option keys differ per framework adapter. The locked rows are data, not a fixed list.
- Whether a framework can pause for a human, stream, or return structured output comes from its adapter. A
  tab whose capability the framework lacks shows why instead of an empty form.
- The link between this page and BR-004: the approval condition and the pause policy are what enforce it.

## Open details

- "Overview" and "Versions" tabs are not briefed yet, so the tab bar leaves them out.
