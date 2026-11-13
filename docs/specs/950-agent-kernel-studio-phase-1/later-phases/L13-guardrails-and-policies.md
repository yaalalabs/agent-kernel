# 13 · Guardrails and policies

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Guard-Guardrails` (main), `Guard-Hooks`, `Guard-SandboxPolicy`, `Guard-Authentication`, `Guard-Guardrails-Configure` |
| Canvas page | Guard |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static. Tabs are prototype links. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

What the runtime enforces around every agent run: input and output guardrails, the order of hooks including
the fixed system hooks, sandbox policy and authentication. A pipeline diagram at the top makes the enforcement
order explicit.

## Layout

- `AppShell` with Guardrails active. Page header "Guardrails and policies", tabs Guardrails, Hooks, Sandbox
  policy, Authentication, and a primary "Add guardrail".
- Guardrails tab: a full-width pipeline card, then a wide column of provider cards beside a narrow column of
  activity.

## Content

**`Guard-Guardrails`**
- Card "Enforcement pipeline": five stages left to right, joined by arrows.
  1. "Request".
  2. "Input guardrails": "OpenAI Guardrails · PII detection" on, "OpenAI Guardrails · Jailbreak" on.
  3. "Agent run": chips triage, billing, kb-researcher.
  4. "Output guardrails": "Walled AI · Safety" on, "Walled AI · PII redaction" on.
  5. "Reply".
  A caption: "Guardrails run as system hooks around every run on every surface: REST, Slack, WhatsApp, Gmail,
  MCP, A2A".
- Provider cards, each with the real logo, a status, a policy chip row and an "Applies to" row:

| Provider | Status | Policies | Applies to |
|----------|--------|----------|------------|
| OpenAI Guardrails | connected | PII detection, Jailbreak, Moderation | all agents, input |
| Walled AI | connected | Safety, PII redaction | all agents, output |
| Amazon Bedrock Guardrails | not connected | "Guardrail ID and version from AWS" | a "Connect" button |

- Card "Recent blocks": "37 today" with a seven-day sparkline, then five rows: time, agent, channel, reason
  ("PII detected: email", "Jailbreak attempt", "Off-topic") and an outcome chip, "Redacted" or "Blocked".
- Card "Block rate by channel": Slack, WhatsApp, Gmail, REST as `BarMeter`s. Values are placeholders until
  real data exists: `[RATE]`.

**`Guard-Hooks`**
- Two ordered lists, "Pre-hooks (run in this order)" and "Post-hooks (run in this order)". System hooks carry
  a lock. A note: "System hooks cannot be reordered".
- Pre: 1 "Input guardrail · system", 2 "Multimodal attachments · system", 3 "Sandbox task events · system",
  4 "RAG context injector · triage, kb-researcher".
- Post: 1 "Output guardrail · system", 2 "A2UI labelling · system", 3 "Signature footer · all agents", with a
  chip "filters stream events".

**`Guard-SandboxPolicy`**
- An `InlineBanner`: "Fail-closed: a policy the provider cannot enforce blocks the run".
- A `DataTable`:

| Profile | Provider | Isolation | Network | Filesystem | CPU / memory | Languages | Package installs | Runs as |
|---------|----------|-----------|---------|------------|--------------|-----------|------------------|---------|
| python-data | docker | container | off | workspace only | 1 vCPU / 512 MB | python | allowed | agent |
| shell-ops | kubernetes | pod | egress allowlist | read-only | 2 vCPU / 1 GB | python, bash | denied | end user (RBAC) |

- A side panel editing python-data.

**`Guard-Authentication`**
- Card "Validator": select "JWT with JWKS"; fields "Issuer", "Audience", "JWKS URL"; "User id claim": `sub`.
- Card "Required on": REST, WebSocket, Threads, Schedules, AG-UI checked; MCP unchecked.
- Card "Per-user scoping": toggles "Threads" and "Schedules" on. Helper "Users only see their own threads and
  tasks".

**`Guard-Guardrails-Configure`**
- A modal "Configure OpenAI Guardrails": toggles for PII detection (with entity chips Email, Phone, Card
  number), Jailbreak, Moderation and Off-topic (with a field "Allowed topics"); a select "On block: reply with
  message" and the message; "Cancel" and "Save".

## Behaviour

- Tabs link the four tab artboards. "Configure" opens `Guard-Guardrails-Configure`.
- A row in "Recent blocks" goes to `Operate-Traces-Blocked`.

## Tweaks

- `pipeline`: diagram or compact list.

## Handoff notes

- The pipeline order is the runtime's real order: agent pre-hooks and system pre-hooks, the runner, system
  post-hooks and agent post-hooks. The output guardrail runs before A2UI labelling.
- These screens enforce BR-006, BR-007, BR-009 (the Signature footer hook) and BR-010 (the sandbox profile).
- AG-UI always requires authentication; it has no anonymous mode.
