---
sidebar_position: 4
---

# Scheduled Tasks

Agent Kernel can **defer and repeat chat execution**: a chat request that carries a `schedule` block is
not run — it is registered as a scheduled task and acknowledged with **HTTP 202**. When an occurrence is
due, the configured provider delivers the stored prompt into the input queue as a plain chat request, and
the normal execution path runs it.

## Overview

| Concern | What it means |
| --- | --- |
| **Enablement** | The presence of a `schedule` block in `config.yaml`. No code change, no handler to mount. |
| **Creation** | Three paths, one implementation: the `schedule` block on a chat request, the `create_schedule` agent tool, or a direct `ScheduleManager` call. There is deliberately **no** `POST /api/v1/schedules`. |
| **Provider** | Owns the timers and fires each occurrence — `local` (in-process thread) or `eventbridge` (AWS EventBridge Scheduler). |
| **Store** | Persists the task records — `in_memory`, `redis`, `valkey`, or `dynamodb`. |
| **Management** | `GET` / `PUT` / `DELETE /api/v1/schedules` for listing, amending, pausing and cancelling. |
| **Ownership** | Every task belongs to a `user_id`; reads and changes are checked against it. |

### Key Design Decisions

- **A schedule block means "not now".** The check runs at the top of all four `ChatService` entry points,
  before validation and agent selection, so every chat surface behaves identically. The caller gets an
  acknowledgement carrying the task id, not an agent reply.
- **`user_id` is required.** It is the owner the task is stored under and the identity later reads and
  changes are checked against. A creation without one is a 400.
- **The occurrence is a plain chat request.** The fired trigger carries no `schedule` key — otherwise
  firing a schedule would register another one.
- **Deferred requests create no thread.** `AgentThreadRequestHandler` checks for the `schedule` block
  before recording, so a deferral neither creates a thread nor records messages. The occurrences that
  later fire do.
- **The provider and store are validated as a pair at startup**, not at first use — see
  [Topology Constraints](#topology-constraints).

:::caution Scheduling needs the queue pipeline
Occurrences are delivered *into the input queue*, so scheduling requires the queue-mode execution
pipeline. On a laptop the `in_memory` transport satisfies this inside one process; on AWS it means
`queue_mode = true`.
:::

## Enabling Scheduling

Add a `schedule` block to `config.yaml`. A bare block works — its defaults (`local` provider,
`in_memory` store) are what local development needs:

```yaml
schedule:
  provider:
    type: local           # local | eventbridge, or a dotted path to a ScheduleProvider
  store:
    type: in_memory       # in_memory | redis | valkey | dynamodb, or a dotted path to a ScheduleStore
  # agents: [planner]     # agents the schedule tools attach to; omitted = all agents

execution:
  mode: rest_sync
  queues:
    type: in_memory
```

Nothing in `app.py` mentions scheduling. `RESTAPI.run()` picks up the block, mounts the management
routes, and resolves the provider/store pairing at startup:

```python
from agentkernel.api import RESTAPI

if __name__ == "__main__":
    RESTAPI.run()
```

Cron parsing needs the `schedule` extra:

```bash
pip install "agentkernel[schedule]"
```

## Chat Request Fields

The `schedule` block on any JSON chat request (`POST /api/v1/chat`):

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `at` | string | — | ISO-8601 **local wall-clock** timestamp for a one-time run. No UTC offset; must be in the future. |
| `cron` | string | — | Standard **5-field** cron expression for a recurring run. |
| `timezone` | string | `UTC` | IANA timezone the expression is evaluated in. |
| `session_mode` | `reuse` \| `new` | `reuse` | Continue the originating session, or give each occurrence a fresh one. |

Exactly one of `at` / `cron` must be given.

:::note Multipart requests cannot carry a schedule
The three multipart chat routes take no `schedule` form field. Schedule a chat over the JSON route.
:::

### Deferring a one-time chat

```bash
curl -i -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send me the daily summary", "session_id": "ses-1", "user_id": "alice",
       "schedule": {"at": "2030-01-31T09:00:00", "timezone": "Asia/Colombo"}}'
```

The acknowledgement comes back as **202**, not 200 — the request was accepted, not executed:

```http
HTTP/1.1 202 Accepted
content-type: application/json

{"result":"{\"status\": \"SCHEDULED\", \"scheduled_task_id\": \"74ca19a5-...\", \"session_id\": \"ses-1\"}","session_id":"ses-1"}
```

The 202 surfaces on every REST surface: direct mode, through the pipeline waiter/poller, and on ECS
(where the queue runners forward it as a `status_code` attribute). Streaming surfaces yield the
acknowledgement as a single terminal chunk — deliberately not an error chunk, since deferring was the
requested outcome.

### Deferring a recurring chat

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send the weekly report", "session_id": "ses-2", "user_id": "alice",
       "schedule": {"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"}}'
```

An unusable schedule is rejected at creation rather than at fire time:

```http
HTTP/1.1 400 Bad Request

{"detail":{"error":"schedule 'at' must be in the future: '2020-01-01T09:00:00' has already passed in UTC","session_id":"ses-1"}}
```

## Managing Schedules

```bash
# List a user's schedules, most recently updated first (cursor-paginated)
curl "http://localhost:8000/api/v1/schedules?user_id=alice&limit=20"

# Read one
curl http://localhost:8000/api/v1/schedules/{task_id}
```

A task record reads back as:

```json
{
  "task_id": "ae9a043b-27f7-480f-8655-5903fbfd200a",
  "user_id": "alice",
  "prompt": "Send the weekly report",
  "agent": null,
  "session_id": "ses-2",
  "spec": {"at": null, "cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"},
  "status": "active",
  "provider_ref": "ae9a043b-27f7-480f-8655-5903fbfd200a",
  "created_at": "2026-08-18T07:04:04.177184+00:00",
  "updated_at": "2026-08-18T07:04:04.178100+00:00",
  "last_triggered_at": null,
  "trigger_count": 0,
  "last_request_id": null
}
```

`status` is one of `active`, `paused`, `completed` (a fired one-time task) or `cancelled`.
`trigger_count`, `last_triggered_at` and `last_request_id` track occurrences — `last_request_id`
correlates a task with the run it produced.

### Amending

`PUT` replaces the **full amendable state** rather than merging, so send every value including the ones
that are not changing. An omitted occurrence field clears it. `status` covers only the paused/active
switch — a paused schedule keeps its record but stops firing:

```bash
curl -X PUT http://localhost:8000/api/v1/schedules/{task_id} \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send the weekly report", "cron": "0 8 * * 1", "timezone": "Asia/Colombo",
       "session_mode": "new", "status": "paused"}'
```

An amendment that names **none** of `at` / `cron` / `timezone` / `session_mode` leaves the occurrence
rule untouched — that is how a prompt-only change works.

### Cancelling

```bash
curl -X DELETE http://localhost:8000/api/v1/schedules/{task_id}
```

The record survives as the audit trail, so the response is the task with `"status": "cancelled"`.

## Agent Tools

When the block is present, Agent Kernel injects five system tools and their guidance into the agent's
system prompt, so an agent can defer work when a user asks it to — agent authors never describe these
tools themselves:

`create_schedule` · `list_schedules` · `get_schedule` · `update_schedule` · `delete_schedule`

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Every weekday at 8am in Asia/Colombo, remind me to review the overnight alerts.",
       "session_id": "ses-3", "user_id": "alice"}'
```

Every tool acts as the **acting user** — the `user_id` of the run that invoked it — so an agent can
never reach another user's schedules. A run with no user identity gets an error result rather than an
anonymous create. Scope the tools to specific agents with `schedule.agents`:

```yaml
schedule:
  agents: [planner]   # omitted = all agents
```

## Authorization

The management routes are **open** until an `Authoriser` is configured. Supply a subclass that validates
the Bearer token against your authentication provider and resolves the caller's `user_id`, then boot
through the IO handler:

```python
from agentkernel.auth import Authoriser
from agentkernel.pipeline import IOHandler


class MyAuthoriser(Authoriser):
    def authorise(self, token: str) -> str | None:
        return resolve_user_from(token)  # None rejects the token


if __name__ == "__main__":
    IOHandler.run(authoriser=MyAuthoriser())
```

With an `Authoriser` configured, listings are forced to the resolved user and reading or changing another
user's schedule is rejected with 403. If you already have an `AuthValidator`, wrap it rather than writing
a second implementation:

```python
from agentkernel.auth import AuthValidatorAuthoriser

IOHandler.run(authoriser=AuthValidatorAuthoriser(MyValidator()))
```

:::caution Open until configured
Without an `Authoriser`, any caller can list and change any user's schedules by passing `user_id`. Expose
these routes publicly only behind one.
:::

## Providers

| Provider | Durability | Transport | Use for |
| --- | --- | --- | --- |
| `local` | Armed occurrences are lost on restart | `in_memory` only | Local development, single-process demos |
| `eventbridge` | AWS owns the timers; any process with the same config can amend or cancel | `sqs` only | Production on AWS |

The `local` provider runs one daemon thread per process over a heap of armed occurrences. The
`eventbridge` provider registers one EventBridge Scheduler schedule per task named `ak-<task_id>`,
translating `at` to an `at(...)` expression and 5-field cron to the 6-field AWS flavour. A fired one-time
schedule is retired by AWS (`ActionAfterCompletion: DELETE`); the store record remains the audit trail.

```yaml
schedule:
  provider:
    type: eventbridge
  store:
    type: dynamodb
```

:::note AWS cron accepts only one day field
EventBridge rejects a schedule constraining both day-of-month and day-of-week. A 5-field cron that
constrains both is refused at creation with a 400.
:::

## Storage Backends

```yaml
# Redis
schedule:
  store:
    type: redis
    redis:
      url: redis://localhost:6379
      prefix: "ak:schedule:"
      ttl: 0                     # 0 disables expiry (the default)

# Valkey (Redis-protocol compatible; requires the `valkey` extra)
schedule:
  store:
    type: valkey
    valkey:
      url: valkey://localhost:6379

# DynamoDB — table needs partition key `task_id` (S), no sort key
schedule:
  store:
    type: dynamodb
    dynamodb:
      table_name: ak-agent-schedules
```

:::note TTL defaults to 0, unlike threads
A task that silently expired would stop firing with no audit trail, so schedule records never expire
unless you set a TTL explicitly.
:::

## Topology Constraints

`ScheduleManager` validates the pairing at startup and fails the boot rather than the first request:

| Combination | Rejected because |
| --- | --- |
| `local` provider + a broker transport (`sqs`/`kafka`/`nats`) | The heap of armed occurrences is reachable only from its own process, so the management routes would amend timers a different process owns — a cancellation would report success while the timer kept firing. |
| `local` provider + a shared store | Same split: the records and the timers must live together. |
| `in_memory` store + a broker transport | The records themselves would be split across the runner and IO-handler processes. |
| `eventbridge` provider + a non-`sqs` transport | Delivery is baked into the schedule registration as an SQS target. |
| `eventbridge` provider with `group_name`, `role_arn` or `queue_arn` missing | Nothing to register schedules against. |

## Deploying Scheduling

Deploying scheduling takes **two** steps, the same split as session and thread storage — your
application declares *which* backends, Terraform provisions them and supplies *where* they live:

1. Declare the backends in `config.yaml`: `schedule: {provider: {type: eventbridge}, store: {type: dynamodb}}`.
2. Set the matching Terraform flags, which provision the backends and inject their coordinates:

| Cloud | Flag | Provisions | Injects |
|---|---|---|---|
| AWS serverless + containerized | `enable_scheduling` | An EventBridge Scheduler schedule group, the execution role Scheduler assumes to deliver triggers to the input queue, and `scheduler:*Schedule` + `iam:PassRole` on both roles | `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__GROUP_NAME`, `__ROLE_ARN`, `__QUEUE_ARN` |
| AWS serverless + containerized | `create_dynamodb_schedule_table` | A DynamoDB table (partition `task_id`, no sort key, no GSI, TTL on `expiry_time`) | `AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME` |

```hcl
queue_mode                     = true
enable_scheduling              = true
create_dynamodb_schedule_table = true
```

You do not need to set the group, role or table names yourself — Terraform generates them and passes
them in.

:::warning Setting the flags without declaring the backends runs scheduling locally
`AKConfig.schedule` is absent until something populates it, and any `AK_SCHEDULE__*` variable is enough
to populate it — but `provider.type` and `store.type` then fall back to their `local` / `in_memory`
defaults. So the Terraform flags *without* a `schedule:` block in `config.yaml` give you an in-process
scheduler whose timers die with the container, while the provisioned group and table sit unused, with no
error. Declare both types and this cannot happen.

The reverse mistake is safe: declaring the types *without* setting the flags fails loudly at startup —
`AKConfigError` on the missing `group_name` / `role_arn` / `queue_arn` — because no coordinates were
injected.
:::

:::note `enable_scheduling` flips the input queue to content-based deduplication
EventBridge Scheduler cannot set a `MessageDeduplicationId`, so without content-based dedup two
occurrences carrying an otherwise identical body would collapse into one inside the 5-minute window.
This is an in-place update on an existing queue and does not affect application senders, which always
send an explicit `MessageDeduplicationId` — that takes precedence. The output queue is untouched.
:::

## Trigger Contract

Each occurrence arrives on the input queue as a plain chat request. The manager freezes one body per
task at create/amend time and the provider substitutes the occurrence placeholders when it fires:

```json
{"prompt": "...", "agent": null, "user_id": "alice",
 "session_id": "ses-2",
 "scheduled_task_id": "<task_id>",
 "request_id": "<per-occurrence id>",
 "scheduled_time": "<occurrence time>"}
```

- With `session_mode: new`, `session_id` becomes `ak-sched-<task_id>-<occurrence_time>`.
- **No `schedule` key** — the occurrence runs, it does not register another schedule.
- **Metadata travels in the body, not in message attributes.** EventBridge Scheduler cannot set SQS
  message attributes, and the local provider deliberately matches that, so both exercise the runners'
  body-fallback path for `request_id` and `user_id`.
- `schedule`, `scheduled_task_id` and `scheduled_time` never reach the agent as unknown context.

## Examples

- [`examples/api/schedule-openai`](https://github.com/yaalalabs/agent-kernel/tree/main/examples/api/schedule-openai) —
  a runnable REST API with the `local` provider and `in_memory` store, showing deferral, the management
  routes, and an agent that schedules work itself.
