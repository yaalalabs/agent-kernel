# 03 · Dashboard

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Home-Dashboard` (main), `Home-Dashboard-Empty`, `Home-Dashboard-AgentFinished` |
| Canvas page | Home |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static with navigation links |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The first screen after sign-in. It answers three questions at a glance: is the system healthy, what does it
look like, and what needs a human.

## Layout

`AppShell` with Home active. The main area is a grid of tiles:

1. A row of four KPI tiles.
2. A wide "System map" tile beside a narrower "Deployments" tile.
3. A wide "Recent runs" tile beside a narrower "Needs attention" tile.

## Content

**KPI tiles** (`KPITile`)

| Label | Value | Delta |
|-------|-------|-------|
| Runs today | 12,480 | +8% vs yesterday (good) |
| p95 latency | 2.4 s | -0.3 s (good) |
| Guardrail blocks | 37 | +12 (needs a look) |
| Est. LLM cost | $184.20 | on budget (neutral) |

**System map.** A read-only canvas preview built from the real canvas components: Slack, WhatsApp and Gmail
channel nodes route to triage; handoff edges go to billing and kb-researcher; the Help Center knowledge node
is bound to kb-researcher; guardrail shields sit on triage's input and output; a deployment frame reads
"AWS ECS Fargate · queue mode · SQS". A ghost button "Open canvas".

**Deployments.** Two rows: "Production · AWS ECS Fargate", healthy, "3 runners", with a small queue-depth
sparkline; "Staging · Kubernetes (Helm)", "Deploying v0.9.15 · 63%", with a progress bar.

**Recent runs** (`DataTable`). Columns: Time, Channel, Agent, Status, Latency, Tokens. Six rows mixing Slack,
WhatsApp, REST and Gmail. Statuses: Completed, "Paused · awaiting approval", "Blocked by guardrail".

**Needs attention.** Four rows, each with an icon and a link:
- "2 runs paused for approval", link "Review".
- "Handoff routing suite is below the gate (88% < 90%)".
- "SLACK_BOT_TOKEN rotates in 3 days".
- "Staging deploy in progress".

## Behaviour

- "Open canvas" goes to `Builder-Canvas`. "Review" goes to `Connect-Playground`.
- A row in "Recent runs" goes to `Operate-Traces`. The Deployments tile goes to `Operate-Deployments`.
- The evaluation line goes to `Operate-Evaluations`. The secret line goes to `Settings-Secrets`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Home-Dashboard-Empty` | first | A brand-new project. The System map tile is an `EmptyState`: "No agents yet", with "Open canvas" and the AI button "Describe it with AI". KPI values read "n/a". Recent runs shows one line: "Runs will appear here after the first message". |
| `Home-Dashboard-AgentFinished` | second | Story moment A. A slim banner under the top bar, AI-styled: "Claude Code finished: added agent billing and 2 tools. Review 3 canvas changes", with a "Review" link and a close control. |

## Tweaks

- `systemMap`: shown or hidden (the tile row collapses to Deployments at full width).

## Handoff notes

- The KPI values are fixture data. In the product they come from the tracing provider and the queue.
