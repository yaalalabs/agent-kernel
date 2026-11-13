# 19 · Schedules

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Operate-Schedules` (main), `Operate-Schedules-RunOnce`, `Operate-Schedules-Empty` |
| Canvas page | Operate |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static with links. The cron builder updating the next occurrences is good to have. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

Deferred and recurring agent runs. A schedule is a chat request with a time rule, a timezone and a session
mode. Agents can create schedules themselves through their tools, so each row shows where it came from.

## Layout

- `AppShell` with Schedules active.
- Main area: a header, filter chips and a table. A "New schedule" panel docked on the right.

## Content

**Header.** "Schedules", chips "Provider: EventBridge Scheduler" and "Store: DynamoDB", a primary "New
schedule". Filter chips: All, Active, Paused, Completed.

**Table** (`DataTable`). Columns: Task, Agent, Schedule, Timezone, Session, Next run, Last run, Status. Each
schedule shows its expression and a plain-language line. A row menu at the end: "Run now", "Pause", "Edit",
then a danger "Delete".

| Task | Agent | Schedule | Timezone | Session | Next run | Last run | Status |
|------|-------|----------|----------|---------|----------|----------|--------|
| Daily support digest: "Summarise yesterday's Slack threads and post to #support-leads" | triage | `0 8 * * 1-5` · Weekdays at 08:00 | Europe/London | New per run | Fri 13 Nov 08:00 | Success, 2 h ago | Active |
| Refund reconciliation | billing | `0 */6 * * *` · Every 6 hours | UTC | Reuse session | Today 18:00 | Success | Active, with an `AIBadge` "Created by agent" |
| Migrate help bundle | kb-researcher | at 2026-11-14 02:00 · Once | UTC | New per run | Sat 14 Nov 02:00 | Not yet | Active |
| Weekly KPI email | triage | `0 9 * * 1` · Mondays at 09:00 | Europe/London | New per run | | Paused | Paused |
| Backfill tickets | kb-researcher | at 2026-11-01 01:00 · Once | UTC | Reuse session | | Completed 1 Nov | Completed |

The "Created by agent" badge has a tooltip: "Created by billing via create_schedule · session s_12ab".

**New schedule panel.** "Prompt" ("What should the agent do?"); "Agent: triage"; a read-only "Owner:
amitha@acme.example"; a segmented control "Run once (at)" / "Repeat (cron)", the second active; the expression
`0 8 * * 1-5` with a `CronBuilder` of five selects (minute, hour, day, month, weekday); "Next 5 occurrences"
as a list of dates; "Timezone: Europe/London"; "Session": "New session per occurrence" (selected) or "Reuse
this session"; a note "Fires through EventBridge Scheduler into the Production input queue"; "Cancel" and a
primary "Create schedule".

## Behaviour

- The segmented control goes to `Operate-Schedules-RunOnce`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Operate-Schedules-RunOnce` | first | The panel in "Run once (at)" mode: a date field and a time field replace the expression and builder; "Next 5 occurrences" becomes a single "Fires at" line. |
| `Operate-Schedules-Empty` | first | No rows. An `EmptyState`: "No schedules yet", "Schedule a prompt to run later or on a recurring basis. Agents can also create schedules with the create_schedule tool.", and "New schedule". |

## Tweaks

- `panel`: docked or closed.

## Handoff notes

- Providers are `local` and `eventbridge`; stores are in-memory, Redis, Valkey and DynamoDB. The local
  provider only works in a single-process deployment.
- A user sees only their own schedules when authentication is on. An agent creates schedules as the acting
  user.
- "Daily support digest" is what enforces BR-011.
